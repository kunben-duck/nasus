# US-EXWEB-CHAT Chat stream contract verification fixture
Description: This is a Nasus verification fixture, not an authoritative exweb business requirement.
Description: The pinned repository declares POST /api/v1/finance/chat/stream in ChatController.java.
## Acceptance criteria
AC-EXWEB-1: A future runtime contract test should check the response content type for a valid chat stream request.
## Business rules
BR-EXWEB-1: Proposed fixture rule: chat requests require authentication; runtime authorization has not been verified.
## Notes
The expected behavior above is a proposed fixture oracle. Static route discovery does not prove that the endpoint runs or satisfies it.
