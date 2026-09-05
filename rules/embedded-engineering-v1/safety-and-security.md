# Safety And Security Rules

Do not add secrets, private keys, production certificates or credentials to
source files, spec files, task research, logs or test output.

Security-sensitive areas include:

* OTA download and verification.
* secure certificate/key storage.
* encryption, HMAC, signature and downgrade-prevention code.
* diagnostic security access.
* any file under a `key/` directory or with a private-key filename.

Rules:

* Do not print key material in logs.
* Do not quote private key contents in AI responses.
* Prefer existing secure storage APIs for certificate and key material.
* Changes to verification, signature, encryption or downgrade behavior must
  include failure-path validation.
* Flash, eFuse and production signing require explicit human confirmation.
