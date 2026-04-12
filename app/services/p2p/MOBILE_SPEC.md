# Lucie Companion — Mobile App Specification

## Overview
Mobile companion app for validating crypto orders from Lucie AI assistant.
Communicates via encrypted P2P over local Wi-Fi network.

**Target platforms:** iOS (SwiftUI) / Android (Kotlin Compose) / Cross-platform (Flutter)
**Recommended:** Flutter (single codebase, fastest time-to-market)

---

## 1. Pairing Flow

### Step 1: QR Code Scan
- User opens Lucie companion app
- Taps "Pair with Lucie"
- Camera opens to scan QR code displayed by Lucie
- QR contains JSON: `{"ip": "192.168.x.x", "port": 8765, "pubkey": "<64 hex chars>"}`

### Step 2: X25519 Handshake
```
Mobile                              Lucie
  |                                   |
  |-- WebSocket connect ------------->|
  |                                   |
  |-- HELLO {pubkey, device_name} --->|
  |                                   |
  |<-- HELLO_ACK {pubkey, session_id, |
  |     challenge} -------------------|
  |                                   |
  |   [Both derive shared key via     |
  |    X25519 + HKDF-SHA256]          |
  |                                   |
  |-- AUTH {challenge_response} ----->|  (encrypted)
  |                                   |
  |<-- AUTH_OK -----------------------|  (encrypted)
  |                                   |
  |   [Session established]           |
```

### Key Derivation
```
shared_secret = X25519(mobile_private_key, lucie_public_key)
aes_key = HKDF-SHA256(shared_secret, salt=None, info=b"lucie-p2p-v1", length=32)
```

### Challenge Response
```
response = BLAKE2b(challenge_hex + aes_key, digest_size=32).hex()
```

### Step 3: Secure Session Storage
- Store `session_id`, `aes_key`, `lucie_ip`, `lucie_port` in device Keychain
- On iOS: Keychain Services with `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`
- On Android: EncryptedSharedPreferences or AndroidKeyStore

---

## 2. Message Protocol

### Wire Format (post-handshake)
All messages after AUTH_OK are encrypted:
```json
{"nonce": "<24 hex chars>", "ciphertext": "<hex>"}
```

Decrypted payload is JSON:
```json
{
  "type": "order_pending",
  "payload": { ... },
  "message_id": "uuid",
  "timestamp": 1234567890.0
}
```

### Message Types

| Type | Direction | Description |
|------|-----------|-------------|
| `order_pending` | Lucie → Mobile | New order awaiting approval |
| `order_approve` | Mobile → Lucie | User approves order |
| `order_reject` | Mobile → Lucie | User rejects order |
| `order_executed` | Lucie → Mobile | Order was executed |
| `order_expired` | Lucie → Mobile | Order timed out |
| `order_failed` | Lucie → Mobile | Order execution failed |
| `status_request` | Mobile → Lucie | Request broker status |
| `status_response` | Lucie → Mobile | Broker status response |
| `ping` / `pong` | Both | Keepalive |
| `disconnect` | Both | Clean disconnect |

### Order Pending Payload
```json
{
  "order_id": "uuid",
  "exchange": "binance",
  "symbol": "BTC/EUR",
  "side": "buy",
  "order_type": "market",
  "quantity": 0.01,
  "price_eur": 62000.0,
  "total_eur": 620.0,
  "timeout_s": 300,
  "remaining_s": 295.3,
  "created_at": 1234567890.0
}
```

### Order Approve Payload
```json
{
  "order_id": "uuid",
  "token": "<32 hex chars>"
}
```

### Order Reject Payload
```json
{
  "order_id": "uuid",
  "token": "<32 hex chars>",
  "reason": "Optional rejection reason"
}
```

---

## 3. Mobile UI Screens

### Screen 1: Pairing
- Camera viewfinder for QR scan
- Manual IP entry fallback
- Connection status indicator
- "Paired with Lucie on 192.168.x.x" confirmation

### Screen 2: Dashboard (Main)
- Connection status badge (green/red)
- Pending orders count
- List of pending orders (cards):
  - Exchange logo + symbol (e.g., "BTC/EUR")
  - Side indicator (green "BUY" / red "SELL")
  - Amount: "0.01 BTC"
  - Total: "620.00 EUR"
  - Countdown timer (circular progress)
  - [Approve] / [Reject] buttons
- Pull-to-refresh

### Screen 3: Order Detail
- Full order details
- Risk check results (if available)
- [Approve] button (requires biometric)
- [Reject] button + reason input
- Countdown timer

### Screen 4: History
- List of past orders with status badges
- Filter by: approved, rejected, expired, failed
- Tap for detail

### Screen 5: Settings
- Paired device info
- Unpair button
- Notification preferences
- Biometric settings

---

## 4. Security Requirements

### Biometric Authentication
- **Required before every approval**
- iOS: FaceID / TouchID via `LocalAuthentication` framework
- Android: BiometricPrompt API
- Fallback: device PIN/password
- Never store approval tokens — derive from session key at approval time

### Network Security
- WebSocket connection over local Wi-Fi only
- All messages encrypted with AES-256-GCM
- Session key derived via X25519 ECDH
- No data sent to internet servers

### Key Storage
- iOS: Keychain with hardware-backed protection
- Android: AndroidKeyStore (hardware-backed if available)
- Keys never leave the device

### Reconnection
- On disconnect, attempt reconnection every 5 seconds (max 12 attempts = 1 minute)
- Use stored session data from Keychain
- If session expired on Lucie side, re-pair via QR code
- Pending orders survive disconnection (stored in Lucie's encrypted SQLite)

---

## 5. Push Notifications (Local)

- Use local notifications (no server required)
- Trigger notification when `order_pending` received while app is backgrounded
- Notification content: "Lucie: Approve BTC/EUR buy for 620 EUR?"
- Tapping notification opens app to order detail

---

## 6. Flutter Implementation Notes

### Dependencies
```yaml
dependencies:
  web_socket_channel: ^2.4.0
  cryptography_flutter: ^2.0.0  # Or pointycastle for X25519
  mobile_scanner: ^3.0.0  # QR code scanning
  local_auth: ^2.1.0  # Biometric
  flutter_secure_storage: ^9.0.0  # Keychain/KeyStore
  flutter_local_notifications: ^16.0.0
```

### State Management
- Provider or Riverpod for connection state
- Stream-based order updates from WebSocket

### Architecture
```
lib/
  main.dart
  models/
    p2p_message.dart
    pending_order.dart
  services/
    p2p_client.dart      # WebSocket + crypto
    key_manager.dart     # X25519 + HKDF
    secure_storage.dart  # Keychain wrapper
    biometric_auth.dart  # FaceID/TouchID
  screens/
    pairing_screen.dart
    dashboard_screen.dart
    order_detail_screen.dart
    history_screen.dart
    settings_screen.dart
  widgets/
    order_card.dart
    countdown_timer.dart
    connection_badge.dart
```

---

## 7. Configuration (Lucie side)

### config.yaml
```yaml
crypto:
  require_approval: true
  approval_timeout_seconds: 300
  p2p:
    enabled: true
    port: 8765
    max_sessions: 1
    session_timeout_seconds: 3600
```

### Pairing Procedure
1. User says "Lucie, affiche le QR code pour l'appairage"
2. Lucie generates QR code and displays in HUD
3. User scans with mobile app
4. Handshake completes automatically
5. Lucie confirms: "Appareil appaire : iPhone de Mathieu"

---

## 8. Error Handling

| Scenario | Mobile Behavior | Lucie Behavior |
|----------|----------------|----------------|
| Wi-Fi disconnect | Show "Disconnected", auto-reconnect | Keep orders pending |
| App killed | Orders survive on Lucie | Re-pair on next open |
| Lucie restart | Mobile loses connection | Orders persist in encrypted DB |
| Wrong QR code | Show error, re-scan | Reject invalid handshake |
| Biometric fail | Block approval, retry | Order stays pending |
| Timeout | Show "Expired" badge | Auto-cancel order |
