# TODO: Fix Service Lifecycle and ngrok Health

## Issue
No service lifecycle commands to start/stop/check the API service.

## Implementation Steps

- [ ] 1. Add runtime paths to run_service.sh
- [ ] 2. Add usage function
- [ ] 3. Parse mode before setup
- [ ] 4. Add helper functions
- [ ] 5. Implement --status mode
- [ ] 6. Implement --stop mode
- [ ] 7. Implement --background mode
- [ ] 8. Keep foreground behavior
- [ ] 9. Fix run_ngrok.sh path root

## Verification Commands
```bash
bash -n run_service.sh tools/service/run_service.sh
bash -n run_ngrok.sh tools/service/run_ngrok.sh
./run_service.sh --background
./run_service.sh --status
curl -i http://127.0.0.1:8088/health
./run_service.sh --stop
