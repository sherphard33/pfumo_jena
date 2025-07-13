package main

import (
	"encoding/json"
	//"fmt"
	"log"
	//"math/rand"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	mqtt "github.com/mochi-mqtt/server/v2"
	"github.com/mochi-mqtt/server/v2/hooks/auth"
	"github.com/mochi-mqtt/server/v2/listeners"
	"github.com/mochi-mqtt/server/v2/packets"
)

// YearlyYield represents the structure for our yearly yield data.
type YearlyYield struct {
	Year  int     `json:"year"`
	Yield float64 `json:"yield"`
}

// MoveCommand matches the JSON structure sent from the LLM agent
type MoveCommand struct {
	ObjectName     string    `json:"object_name"`
	TargetPosition []float64 `json:"target_position"`
	Duration       float64   `json:"duration"`
	RequestID      string    `json:"request_id"`
}

// MoveCompletionFeedback matches the JSON structure for feedback to the LLM agent
type MoveCompletionFeedback struct {
	ObjectName    string    `json:"object_name"`
	FinalPosition []float64 `json:"final_position"`
	Status        string    `json:"status"`
	Timestamp     string    `json:"timestamp"`
	RequestID     string    `json:"request_id"`
}

// MoveCommandHook is a custom hook to process move commands and send feedback.
type MoveCommandHook struct {
	mqtt.HookBase
	server *mqtt.Server // Reference to the MQTT server to publish messages
}

// ID returns the ID of the hook.
func (h *MoveCommandHook) ID() string {
	return "MoveCommandHook"
}

// Provides indicates the methods that the hook provides.
func (h *MoveCommandHook) Provides(p byte) bool {
	return p == mqtt.OnPublish
}

// OnPublish is called when a PUBLISH packet is received.
func (h *MoveCommandHook) OnPublish(cl *mqtt.Client, pk packets.Packet) (packets.Packet, error) {
	if pk.TopicName == "unity/commands/move" {
		log.Printf("Received move command on topic %s from client %s: %s", pk.TopicName, cl.ID, string(pk.Payload))

		var cmd MoveCommand
		if err := json.Unmarshal(pk.Payload, &cmd); err != nil {
			log.Printf("Error unmarshalling move command: %v", err)
			return pk, nil // Continue processing, but don't send feedback for malformed command
		}

		// In a real scenario, you'd forward this command to Unity or a game server.
		// For this example, we immediately simulate completion and send feedback.
		log.Printf("Simulating move completion for object '%s' to %v (Request ID: %s)",
			cmd.ObjectName, cmd.TargetPosition, cmd.RequestID)

		// Prepare feedback message
		feedback := MoveCompletionFeedback{
			ObjectName:    cmd.ObjectName,
			FinalPosition: cmd.TargetPosition, // Assuming it reaches the target
			Status:        "success",
			Timestamp:     time.Now().Format(time.RFC3339),
			RequestID:     cmd.RequestID,
		}

		feedbackPayload, err := json.Marshal(feedback)
		if err != nil {
			log.Printf("Error marshalling feedback payload: %v", err)
			return pk, nil
		}

		// Publish the completion feedback
		if err := h.server.Publish("unity/feedback/move_complete", feedbackPayload, false, 0); err != nil {
			log.Printf("Error publishing move completion feedback: %v", err)
		} else {
			log.Printf("Published move completion feedback for Request ID %s", cmd.RequestID)
		}
	}
	return pk, nil
}

func main() {
	// Create a channel to receive OS signals.
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)

	// Create a new MQTT server with inline client enabled.
	server := mqtt.New(&mqtt.Options{
		InlineClient: true,
	})

	// Allow all connections.
	_ = server.AddHook(new(auth.AllowHook), nil)

	// Add the custom MoveCommandHook
	moveHook := &MoveCommandHook{server: server}
	err := server.AddHook(moveHook, nil)
	if err != nil {
		log.Fatal(err)
	}

	// Create a TCP listener on a standard port.
	mqtt := listeners.NewTCP(listeners.Config{
		ID:      "mqtt",
		Type:    "mqtt",
		Address: ":1883",
	})
	err = server.AddListener(mqtt)

	if err != nil {
		log.Fatal(err)
	}

	// Start the server
	go func() {
		err := server.Serve()
		if err != nil {
			log.Fatal(err)
		}
	}()

	// Start a goroutine to publish random data.
	// go func() {
	// 	ticker := time.NewTicker(5 * time.Second)
	// 	defer ticker.Stop()
	// 	for {
	// 		<-ticker.C
	// 		// Publish to sludge_pool topics
	// 		ammonia := rand.Float64() * 100
	// 		nitrate := rand.Float64() * 100
	// 		phosphate := rand.Float64() * 100
	// 		chlorine := rand.Float64() * 100
	// 		iron := rand.Float64() * 100
	// 		if err := server.Publish("sludge_pool/ammonia", []byte(fmt.Sprintf("%.2f", ammonia)), false, 0); err != nil {
	// 			log.Printf("error publishing to sludge_pool/ammonia: %v", err)
	// 		} else {
	// 			log.Printf("Published to sludge_pool/ammonia: %.2f", ammonia)
	// 		}

	// 		if err := server.Publish("sludge_pool/nitrate", []byte(fmt.Sprintf("%.2f", nitrate)), false, 0); err != nil {
	// 			log.Printf("error publishing to sludge_pool/nitrate: %v", err)
	// 		} else {
	// 			log.Printf("Published to sludge_pool/nitrate: %.2f", nitrate)
	// 		}

	// 		if err := server.Publish("sludge_pool/phosphate", []byte(fmt.Sprintf("%.2f", phosphate)), false, 0); err != nil {
	// 			log.Printf("error publishing to sludge_pool/phosphate: %v", err)
	// 		} else {
	// 			log.Printf("Published to sludge_pool/phosphate: %.2f", phosphate)
	// 		}

	// 		// Publish to chemical_tank

	// 		if err := server.Publish("chemical_tank/ammonia", []byte(fmt.Sprintf("%.2f", ammonia)), false, 0); err != nil {
	// 			log.Printf("error publishing to chemical_tank/ammonia: %v", err)
	// 		} else {
	// 			log.Printf("Published to chemical_tank/ammonia: %.2f", ammonia)
	// 		}

	// 		if err := server.Publish("chemical_tank/iron", []byte(fmt.Sprintf("%.2f", iron)), false, 0); err != nil {
	// 			log.Printf("error publishing to chemical_tank/iron: %v", err)
	// 		} else {
	// 			log.Printf("Published to chemical_tank/iron: %.2f", iron)
	// 		}

	// 		if err := server.Publish("chemical_tank/chlorine", []byte(fmt.Sprintf("%.2f", chlorine)), false, 0); err != nil {
	// 			log.Printf("error publishing to chemical_tank/chlorine: %v", err)
	// 		} else {
	// 			log.Printf("Published to chemical_tank/chlorine: %.2f", chlorine)
	// 		}
	// 	}
	// }()

	// Set up the HTTP endpoint.
	http.HandleFunc("/yearly_yields", func(w http.ResponseWriter, r *http.Request) {
		yields := []YearlyYield{
			{Year: 2020, Yield: 25.5},
			{Year: 2021, Yield: 26.8},
			{Year: 2022, Yield: 28.1},
			{Year: 2023, Yield: 27.9},
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(yields)
	})

	// Start the HTTP server.
	go func() {
		log.Println("HTTP server started on :8080")
		if err := http.ListenAndServe(":8080", nil); err != nil {
			log.Fatalf("could not start HTTP server: %v", err)
		}
	}()

	// Wait for a signal to gracefully shut down the server.
	log.Println("MQTT Server started on :1883")
	<-sigs
	log.Println("Shutting down server...")
	_ = server.Close()
	log.Println("Server gracefully stopped.")
}
