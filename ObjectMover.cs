using UnityEngine;
using M2MqttUnity;
using uPLibrary.Networking.M2Mqtt.Messages;
using Newtonsoft.Json; // Make sure you have Newtonsoft.Json imported into your Unity project
using System.Collections; // Needed for Coroutines
using System; // For DateTime

public class ObjectMover : M2MqttUnityClient
{
    // Public reference to the object that will be controlled by MQTT commands
    public GameObject controllableObject; 

    // Define JSON message structures
    [Serializable] // Allow Unity to serialize this for debugging, though not strictly necessary for runtime
    public class MoveCommand
    {
        public string object_name;
        public float[] target_position;
        public float duration;
        public string request_id; 
    }

    [Serializable]
    public class MoveCompletionFeedback
    {
        public string object_name;
        public float[] final_position;
        public string status;
        public string timestamp;
        public string request_id; 
    }

    // Internal state for movement interpolation
    private Vector3 currentTargetPosition;
    private Vector3 startPosition;
    private float moveStartTime;
    private float moveDuration;
    private string currentMoveRequestId; // Store the ID for the currently executing move

    // MQTT Topics
    private const string CommandTopic = "unity/commands/move";
    private const string FeedbackTopic = "unity/feedback/move_complete";

    protected override void Start()
    {
        // M2MqttUnityClient's Start method will handle the connection
        base.Start();
        Debug.Log("ObjectMover script started.");
    }

    // Update is called once per frame. No continuous movement logic here now, handled by coroutine.
    protected override void Update()
    {
        base.Update(); // Call ProcessMqttEvents() to handle message queue
    }

    protected override void SubscribeTopics()
    {
        // Subscribe to the command topic from the LLM agent
        client.Subscribe(new string[] { CommandTopic },
            new byte[] { MqttMsgBase.QOS_LEVEL_EXACTLY_ONCE });
        Debug.Log($"Subscribed to topic: {CommandTopic}");

        // You might still want to subscribe to your existing chemical topics if they are relevant
        // client.Subscribe(new string[] { "chemical_tank/ammonia", "chemical_tank/iron", "chemical_tank/chlorine" },
        //    new byte[] { MqttMsgBase.QOS_LEVEL_EXACTLY_ONCE, MqttMsgBase.QOS_LEVEL_EXACTLY_ONCE, MqttMsgBase.QOS_LEVEL_EXACTLY_ONCE });
    }

    protected override void UnsubscribeTopics()
    {
        client.Unsubscribe(new string[] { CommandTopic });
        // client.Unsubscribe(new string[] { "chemical_tank/ammonia", "chemical_tank/iron", "chemical_tank/chlorine" });
    }

    protected override void DecodeMessage(string topic, byte[] message)
    {
        string msg = System.Text.Encoding.UTF8.GetString(message);
        Debug.Log($"Received MQTT message on topic '{topic}': {msg}");

        if (topic == CommandTopic)
        {
            HandleMoveCommand(msg);
        }
        // else if (topic.StartsWith("chemical_tank/")) // Keep existing chemical tank logic if needed
        // {
        //     // Your existing logic for chemical_tank messages
        // }
        else
        {
            Debug.LogWarning($"Received message on unhandled topic: {topic}");
        }
    }

    private void HandleMoveCommand(string jsonMessage)
    {
        if (controllableObject == null)
        {
            Debug.LogError("Controllable object is not assigned in the Inspector!");
            return;
        }

        try
        {
            MoveCommand command = JsonConvert.DeserializeObject<MoveCommand>(jsonMessage);

            // Basic validation: ensure target_position has 3 elements
            if (command.target_position == null || command.target_position.Length != 3)
            {
                Debug.LogError("Invalid target_position received. Must be an array of 3 floats.");
                // Optionally send a failure feedback
                PublishMoveCompletion(command.object_name, controllableObject.transform.position, "failure", command.request_id, "Invalid target position");
                return;
            }

            // Check if the command is for *this* specific controllable object
            // This is important if you have multiple ObjectMover scripts controlling different objects
            if (command.object_name != controllableObject.name)
            {
                Debug.LogWarning($"Ignoring command for object '{command.object_name}'. This script controls '{controllableObject.name}'.");
                return;
            }

            Vector3 targetPos = new Vector3(
                (float)command.target_position[0],
                (float)command.target_position[1],
                (float)command.target_position[2]
            );
            float duration = command.duration > 0 ? command.duration : 2.0f; // Default duration if invalid or not provided

            // Stop any existing movement coroutine to prevent overlapping moves
            StopAllCoroutines(); 
            StartCoroutine(MoveObjectCoroutine(targetPos, duration, command.request_id));

            Debug.Log($"Initiated move for '{command.object_name}' to {targetPos} over {duration} seconds. Request ID: {command.request_id}");
        }
        catch (JsonException ex)
        {
            Debug.LogError($"JSON parsing error for move command: {ex.Message} - Message: {jsonMessage}");
            // No request_id to send feedback for, as parsing failed
        }
        catch (Exception ex)
        {
            Debug.LogError($"Error processing move command: {ex.Message}");
        }
    }

    private IEnumerator MoveObjectCoroutine(Vector3 targetPos, float duration, string requestId)
    {
        startPosition = controllableObject.transform.position;
        currentTargetPosition = targetPos;
        moveDuration = duration;
        moveStartTime = Time.time;
        currentMoveRequestId = requestId; // Store the request ID for completion feedback

        float elapsed = 0f;
        while (elapsed < moveDuration)
        {
            elapsed = Time.time - moveStartTime;
            float t = elapsed / moveDuration;
            // Easing function can be added here, e.g., Mathf.SmoothStep
            controllableObject.transform.position = Vector3.Lerp(startPosition, currentTargetPosition, t);
            yield return null; // Wait for the next frame
        }

        // Ensure it snaps exactly to the final position to avoid floating point inaccuracies
        controllableObject.transform.position = currentTargetPosition;

        Debug.Log($"Object '{controllableObject.name}' finished moving to: {currentTargetPosition}. Request ID: {currentMoveRequestId}");

        // Publish move completion feedback
        PublishMoveCompletion(controllableObject.name, controllableObject.transform.position, "success", currentMoveRequestId);
    }

    private void PublishMoveCompletion(string objName, Vector3 finalPos, string status, string requestId, string errorMessage = null)
    {
        MoveCompletionFeedback feedback = new MoveCompletionFeedback
        {
            object_name = objName,
            final_position = new float[] { finalPos.x, finalPos.y, finalPos.z },
            status = status,
            timestamp = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
            request_id = requestId 
        };

        // Add error message if status is 'failure'
        if (status == "failure" && !string.IsNullOrEmpty(errorMessage))
        {
            // If you want to include custom error messages in the feedback,
            // you'd need to add a string field to MoveCompletionFeedback and populate it here.
            // For now, let's just log it.
            Debug.LogError($"Move completion feedback for {objName} (ID: {requestId}) status: {status}, Error: {errorMessage}");
        }

        string jsonPayload = JsonConvert.SerializeObject(feedback);

        if (client != null && client.IsConnected)
        {
            try
            {
                client.Publish(FeedbackTopic, System.Text.Encoding.UTF8.GetBytes(jsonPayload), MqttMsgBase.QOS_LEVEL_EXACTLY_ONCE, false);
                Debug.Log($"Published move completion feedback for '{objName}' (ID: {requestId}) status: {status}.");
            }
            catch (Exception ex)
            {
                Debug.LogError($"Failed to publish MQTT feedback message: {ex.Message}");
            }
        }
        else
        {
            Debug.LogWarning("MQTT client not connected, unable to publish feedback.");
        }
    }

    protected override void OnConnectionFailed(string errorMessage)
    {
        Debug.LogError($"MQTT Connection failed: {errorMessage}");
    }

    protected override void OnDisconnected()
    {
        Debug.Log("MQTT Disconnected.");
    }

    protected override void OnConnected()
    {
        base.OnConnected();
        Debug.Log("MQTT Connected.");
        // Re-subscribe if connection was lost and re-established
        SubscribeTopics(); // Ensure topics are subscribed after re-connection
    }
}
