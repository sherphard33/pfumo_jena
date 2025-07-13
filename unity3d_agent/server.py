import asyncio
import json
import uuid
import threading
import os
from typing import List, Dict, Any

import paho.mqtt.client as mqtt
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.llms.openai import OpenAI
from llama_index.core.tools import FunctionTool, ToolMetadata
from pydantic import BaseModel, Field


# --- 1. UnityMoverTool Class (Adapted for LlamaIndex) ---
# This class manages the MQTT communication and tracks move completion feedback.
class UnityMoverTool:
    def __init__(self, broker_address: str, port: int = 1883,
                 command_topic: str ="unity/commands/move",
                 feedback_topic: str = "unity/feedback/move_complete"):
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.broker_address = broker_address
        self.port = port
        self.command_topic = command_topic
        self.feedback_topic = feedback_topic

        # Store completed moves feedback
        # Key: request_id
        # Value: The feedback payload
        self.completed_moves = {}
        self.completed_moves_lock = threading.Lock()

        self._connect_mqtt()

    def _connect_mqtt(self):
        """Connects to the MQTT broker and starts the loop."""
        try:
            self.client.connect(self.broker_address, self.port, 60)
            self.client.loop_start() # Start MQTT client loop in background
            print(f"Attempting to connect to MQTT broker at {self.broker_address}:{self.port}")
        except Exception as e:
            print(f"Failed to connect to MQTT broker: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        """Callback for when the client connects to the MQTT broker."""
        if rc == 0:
            print("Connected to MQTT Broker!")
            client.subscribe(self.feedback_topic)
            print(f"Subscribed to feedback topic: {self.feedback_topic}")
        else:
            print(f"Failed to connect, return code {rc}\n")

    def _on_message(self, client, userdata, msg):
        """Callback for when a PUBLISH message is received from the server."""
        if msg.topic == self.feedback_topic:
            try:
                payload = json.loads(msg.payload.decode('utf-8'))
                request_id = payload.get("request_id")

                if request_id:
                    with self.completed_moves_lock:
                        self.completed_moves[request_id] = payload
                    print(f"Received move completion feedback for ID '{request_id}': {payload}")
                else:
                    print(f"Received move completion feedback without request_id: {payload}")
            except json.JSONDecodeError:
                print(f"Failed to decode JSON from feedback message: {msg.payload}")
        else:
            print(f"Received message on unhandled topic: {msg.topic}")

    def initiate_object_move_3d(self, object_name: str, target_position: List[float], duration: float = 2.0) -> Dict[str, Any]:
        """
        Sends a command to move a specified object in the 3D environment to a target coordinate,
        interpolating smoothly. This tool initiates the movement but does not wait for its completion.
        Use `check_move_status` to determine if the movement has finished.

        Args:
            object_name (str): The name or ID of the 3D object to be moved (e.g., "MyCube").
            target_position (List[float]): A list of three floating-point numbers [x, y, z] for the destination.
            duration (float, optional): The time in seconds for the movement. Defaults to 2.0 seconds.

        Returns:
            Dict[str, Any]: A dictionary indicating the status of the command and the request ID.
        """
        if not (isinstance(target_position, list) and len(target_position) == 3 and
                all(isinstance(coord, (int, float)) for coord in target_position)):
            return {"status": "error", "message": "Invalid target_position. Must be a list of 3 numbers."}
        if not (isinstance(duration, (int, float)) and duration > 0):
            return {"status": "error", "message": "Invalid duration. Must be a positive number."}

        request_id = str(uuid.uuid4()) # Generate a unique ID for this request

        payload = {
            "object_name": object_name,
            "target_position": target_position,
            "duration": duration,
            "request_id": request_id # Include the request ID in the command
        }

        try:
            self.client.publish(self.command_topic, json.dumps(payload))
            return {
                "status": "success",
                "message": f"Move command initiated for {object_name} to {target_position} over {duration} seconds.",
                "object_name": object_name,
                "requested_target_position": target_position,
                "request_id": request_id
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to send MQTT message: {e}"}

    def check_move_status(self, request_id: str) -> Dict[str, Any]:
        """
        Checks the completion status of a previously initiated object movement using its request ID.
        This tool will return the completion feedback if the movement has completed for the given request ID.
        If the movement is still in progress or the request ID is not found, it will indicate that.

        Args:
            request_id (str): The unique ID of the specific move request to check.

        Returns:
            Dict[str, Any]: A dictionary containing the status ("completed", "in_progress", "not_found")
                            and the feedback data if completed.
        """
        with self.completed_moves_lock:
            feedback = self.completed_moves.get(request_id)
            if feedback:
                del self.completed_moves[request_id] # Consume the feedback once retrieved
                return {"status": "completed", **feedback}
            else:
                return {"status": "in_progress", "message": f"Move for request_id {request_id} not yet completed or found."}

    def disconnect(self):
        """Disconnects the MQTT client."""
        self.client.loop_stop()
        self.client.disconnect()
        print("Disconnected from MQTT broker.")


# --- Pydantic Schemas for Tools ---
class InitiateMoveSchema(BaseModel):
    """Initiates a smooth movement for a 3D object to a target position."""
    object_name: str = Field(..., description="The name or ID of the 3D object to be moved (e.g., 'MyCube').")
    target_position: List[float] = Field(..., description="A list of three floating-point numbers [x, y, z] for the destination.")
    duration: float = Field(default=2.0, description="The time in seconds for the movement. Defaults to 2.0 seconds.")

class CheckStatusSchema(BaseModel):
    """Checks if a previously initiated 3D object movement has completed."""
    request_id: str = Field(..., description="The unique ID of the specific move request to check, obtained from `initiate_object_move_3d`.")


# --- 2. LlamaIndex Agent Setup ---
async def main():
    # Initialize your UnityMoverTool instance
    # Make sure your GoLang MQTT server is running at this address and port.
    unity_mover = UnityMoverTool(broker_address="localhost", port=1883)

    # Create LlamaIndex FunctionTool objects from the UnityMoverTool methods
    initiate_move_tool = FunctionTool.from_defaults(
        fn=unity_mover.initiate_object_move_3d,
        name="initiate_object_move_3d",
        description=(
            "Sends a command to move a specified object in the 3D environment to a target coordinate, "
            "interpolating smoothly. This tool initiates the movement but does not wait for its completion. "
            "Returns a dictionary with 'status', 'message', 'object_name', 'requested_target_position', and 'request_id'. "
            "The 'request_id' is crucial for tracking the completion of this specific move."
        ),
        tool_metadata=ToolMetadata(
            name="initiate_object_move_3d",
            description="Initiates a smooth movement for a 3D object to a target position.",
            fn_schema=InitiateMoveSchema
        )
    )

    check_status_tool = FunctionTool.from_defaults(
        fn=unity_mover.check_move_status,
        name="check_move_status",
        description=(
            "Checks the completion status of a previously initiated object movement using its request ID. "
            "Returns a dictionary with 'status' ('completed', 'in_progress', 'not_found'). "
            "If 'completed', it also includes 'object_name', 'final_position', 'timestamp', and 'request_id'."
        ),
        tool_metadata=ToolMetadata(
            name="check_move_status",
            description="Checks if a previously initiated 3D object movement has completed.",
            fn_schema=CheckStatusSchema
        )
    )

    # Create the LlamaIndex FunctionAgent
    # This now uses a local LlamaCPP server that exposes an OpenAI-compatible API.
    # Make sure your LlamaCPP server is running.
    llm = OpenAI(
        api_base="http://127.0.0.1:8080/v1",
        api_key="sk-no-key-required", # Can be any string
        temperature=0.0,
    )
    agent = FunctionAgent(
        tools=[initiate_move_tool, check_status_tool],
        llm=llm,
        system_prompt=(
            "You are an AI assistant capable of controlling a 3D object named 'Cube' in a Unity environment. "
            "You can initiate movements and check their completion status. "
            "When asked to move an object, first use `initiate_object_move_3d`. "
            "Then, if the user asks for completion or if you need to perform a subsequent action, "
            "periodically use `check_move_status` with the `request_id` you received from the `initiate_object_move_3d` call. "
            "If a move is still in progress, inform the user and suggest checking again later. "
            "Always refer to the object as 'Cube' unless specified otherwise."
        ),
    )

    # --- 3. Interactive Agent Loop ---
    print("--- Starting LLM Agent Interaction ---")
    print("Enter a command to the agent. For example: 'Move Cube to [0.0, 5.0, 0.0] over 3 seconds.'")
    print("Type 'quit' or 'exit' to end the session.")

    try:
        while True:
            user_input = input("User > ")
            if user_input.lower() in ["quit", "exit"]:
                print("Exiting...")
                break

            if not user_input.strip():
                continue

            response_initiate = await agent.run(user_input)
            print(f"Agent: {response_initiate}")

            # --- Handle Move Completion ---
            # Extract request_id if a move was initiated
            request_id_from_agent = None
            if response_initiate.tool_calls:
                for tool_call in response_initiate.tool_calls:
                    if tool_call.tool_name == "initiate_object_move_3d":
                        tool_output = tool_call.tool_output
                        if hasattr(tool_output, "raw_output") and isinstance(tool_output.raw_output, dict):
                            request_id_from_agent = tool_output.raw_output.get("request_id")
                        else:
                            print(f"Could not extract request_id from tool output: {tool_output}")
                        break

            # If a move was initiated, periodically check for its completion
            if request_id_from_agent:
                print(f"Move initiated with request_id: {request_id_from_agent}. Periodically checking status...")
                for i in range(10):  # Check up to 10 times
                    await asyncio.sleep(1.5)
                    check_prompt = f"Is the move with request ID {request_id_from_agent} complete?"
                    response_check = await agent.run(check_prompt)
                    print(f"Agent (status check): {response_check}")

                    if "completed" in str(response_check).lower():
                        print("Agent confirmed move completed!")
                        break
                else:
                    print("Agent stopped checking. Move may not have completed.")
    except (KeyboardInterrupt, EOFError):
        print("\nSession ended by user.")
    finally:
        # Clean up MQTT connection
        unity_mover.disconnect()
        print("--- LLM Agent Interaction Finished ---")

# Run the agent
if __name__ == "__main__":
    asyncio.run(main())