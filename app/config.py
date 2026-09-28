import os


def _load_local_env() -> None:
	placeholder_values = {
		"",
		"demo-openai-api-key",
		"demo-key",
		"placeholder",
		"changeme",
		"dummy",
		"dummy-key",
	}

	def _is_placeholder(value: str) -> bool:
		normalized = (value or "").strip().lower()
		return normalized in placeholder_values or normalized.startswith("dummy-")

	project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	env_path = os.path.join(project_root, ".env")
	if not os.path.exists(env_path):
		return

	with open(env_path, "r", encoding="utf-8") as handle:
		for raw_line in handle:
			line = raw_line.strip()
			if not line or line.startswith("#") or "=" not in line:
				continue
			key, value = line.split("=", 1)
			key = key.strip()
			value = value.strip().strip('"').strip("'")
			existing = (os.environ.get(key) or "").strip().lower()
			if key and (key not in os.environ or _is_placeholder(existing)):
				os.environ[key] = value


_load_local_env()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "") or os.getenv("AZURE_OPENAI_PROJECT_ENDPOINT", "") or os.getenv("AZURE_OPENAI_ENDPOINT", "")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "") or os.getenv("AZURE_OPENAI_API_VERSION", "")

LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4.1-mini")
LLM_STREAM = os.getenv("LLM_STREAM", "1").strip().lower() not in {"0", "false", "no", "off"}
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "180"))
LLM_MAX_OUTPUT_TOKENS_VISION = int(os.getenv("LLM_MAX_OUTPUT_TOKENS_VISION", "900"))

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "alcuser")
DB_PASSWORD = os.getenv("DB_PASSWORD", "alcpass")
DB_NAME = os.getenv("DB_NAME", "alcohol_label_verification")

# Rate limiting for LLM-backed endpoints (per client IP). Set to 0 to disable a given limit.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "5"))
RATE_LIMIT_PER_DAY = int(os.getenv("RATE_LIMIT_PER_DAY", "50"))

# Optional shared API key required for LLM-backed endpoints. Empty disables the check.
API_KEY = os.getenv("API_KEY", "")

# Simple username/password login gate for the whole service. Both must be set to
# require login; if either is empty, login is disabled (open access).
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")

# Secret used to sign session cookies. Set this explicitly in production so sessions
# survive process restarts; if left empty, a random key is generated at startup
# (existing sessions will be invalidated whenever the process restarts).
SECRET_KEY = os.getenv("SECRET_KEY", "")

# Set to "1" when serving over HTTPS so the session cookie is marked Secure.
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}

