# US-EXWEB-SESSION Read only owned finance chat sessions

Description: Nasus trial draft for exweb commit fe5827f6b76f77ef34918d8b452ee823142332dc. The source is docs/architecture/README.md, lines 315-335, which describes tenant, user and session identity. This is a proposed test design, not a maintainer-approved requirement, authentication guarantee or execution result.

## Acceptance criteria

AC-EXWEB-SESSION-OWNER: The fixture owner can retrieve the session created for that tenant and user. Verify the original session ID to prove that the fixture exists before interpreting isolation checks.
AC-EXWEB-SESSION-USER: A different test user in the same tenant cannot retrieve that fixture session or see it in their own session list.
AC-EXWEB-SESSION-TENANT: The same test user identifier in a different tenant cannot retrieve that fixture session or see it in their own session list.

## Business rules

BR-EXWEB-SESSION-TRIAL: Use only a disposable test environment and synthetic identities. Review the exact denial response and trusted identity mechanism independently before approving an executable oracle. A server error or an empty response alone does not establish isolation.
