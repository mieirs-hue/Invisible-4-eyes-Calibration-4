#include <Arduino.h>
#include <esp_netif.h>
#include <esp_wifi.h>

#ifndef NODE_ID
#define NODE_ID "X"
#endif

#ifndef NODE_LABEL
#define NODE_LABEL "node_unknown"
#endif

// Compact struct to filter out the target data points
struct PacketMetrics {
    uint8_t src_mac[6];
    int8_t rssi;
    uint16_t seq_num;
    uint32_t ie_hash;
};

// Promiscuous mode packet sniffer callback handler
void wifi_sniffer_cb(void* buf, wifi_promiscuous_pkt_type_t type) {
    // We only care about 802.11 Management Frames
    if (type != WIFI_PKT_MGMT) return; 

    const wifi_promiscuous_pkt_t* pkt = (wifi_promiscuous_pkt_t*)buf;
    const uint8_t* payload = pkt->payload;
    const int payload_len = pkt->rx_ctrl.sig_len;

    // Require enough bytes for management header fields we access.
    if (payload_len < 24) return;
    
    // Parse the Frame Control byte to isolate Probe Requests (Type 0, Subtype 4)
    uint8_t frame_control = payload[0];
    uint8_t frame_type = (frame_control & 0x0C) >> 2;
    uint8_t frame_subtype = (frame_control & 0xF0) >> 4;
    
    // Type 0 = Management, Subtype 4 = Probe Request
    if (frame_type == 0 && frame_subtype == 4) {
        int8_t rssi = pkt->rx_ctrl.rssi;
        
        // Extract sequence number from bytes 22-23 (shifted out of fragment bits)
        uint16_t seq_ctrl = static_cast<uint16_t>(payload[22]) |
                            (static_cast<uint16_t>(payload[23]) << 8);
        uint16_t seq_num = seq_ctrl >> 4;
        
        // Extract Transmitter/Source MAC Address (Bytes 10 to 15)
        uint8_t src_mac[6];
        memcpy(src_mac, payload + 10, 6);
        
        // DJB2 Hash representation of Information Elements starting at byte 24
        // This builds a lightweight metadata signature for spatial fingerprinting
        uint32_t ie_hash = 5381;
        if (payload_len > 24) {
            for (int i = 24; i < payload_len; i++) {
                ie_hash = ((ie_hash << 5) + ie_hash) + payload[i];
            }
        }
        
        // Stream optimized JSON directly across the serial bus to the Jetson Orin Nano
        Serial.printf("{\"node\":\"%s\",\"node_label\":\"%s\",\"mac\":\"%02x:%02x:%02x:%02x:%02x:%02x\",\"rssi\":%d,\"seq\":%d,\"ie\":\"%08x\"}\n",
                  NODE_ID, NODE_LABEL,
                      src_mac[0], src_mac[1], src_mac[2], src_mac[3], src_mac[4], src_mac[5],
                      rssi, seq_num, ie_hash);
    }
}

void setup() {
    // Open the serial pipe wide enough to prevent queue lag
    Serial.begin(115200);
    delay(1000);
    
    // Deep-initialize the Espressif Wi-Fi subsystem into non-routing NULL mode
    ESP_ERROR_CHECK(esp_netif_init());
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL)); 
    ESP_ERROR_CHECK(esp_wifi_start());
    
    // Route the raw packets right into our analytical callback hook
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(&wifi_sniffer_cb));
    
    // Set base tracking frequency channel (2.4GHz Channel 1)
    esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE);
    
    // Pulse the initialization check out to the terminal
    Serial.printf("{\"status\":\"NODE_ONLINE\",\"node\":\"%s\",\"node_label\":\"%s\"}\n", NODE_ID, NODE_LABEL);
}

void loop() {
    // Dynamic channel-hopping routine to hunt frames across the entire 2.4GHz spectrum
    static unsigned long last_hop_time = 0;
    static uint8_t current_channel = 1;
    
    // Dwell on each channel for 300ms to catch standard burst intervals
    if (millis() - last_hop_time > 300) {
        current_channel = (current_channel % 11) + 1; // Cycle sequentially 1 through 11
        esp_wifi_set_channel(current_channel, WIFI_SECOND_CHAN_NONE);
        last_hop_time = millis();
    }
}