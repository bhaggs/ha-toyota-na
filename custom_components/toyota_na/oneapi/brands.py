"""Per-brand configuration for the shared ctpa-oneapi backend.

The Subaru values below - login tenant, X-APPBRAND, and the v4/account bootstrap
- come from APK reverse-engineering done independently by @adepssimius and
@keithnet, who arrived at matching findings.

Every value that differs between Toyota and Subaru lives here. Nothing else in
the integration should branch on brand -- if a new difference turns up, add a
field to BrandConfig rather than an `if brand == "S"` at the call site.

Deliberately *not* parameterized, because both brands are confirmed to share
them: the ForgeRock realm and client_id, the OAuth scope and redirect_uri, the
API gateway, the GraphQL/AppSync endpoint and keys, and every endpoint path.
"""
from dataclasses import dataclass

# Shared ForgeRock/OAuth constants. Only the host differs per brand.
REALM_PATH = "realms/root/realms/tmna-native"
CLIENT_ID = "oneappsdkclient"
REDIRECT_URI = "com.toyota.oneapp:/oauth2Callback"
SCOPE = "openid profile write"


@dataclass(frozen=True)
class BrandConfig:
    """Everything that varies between brands on the shared backend."""

    code: str
    """Value sent as X-BRAND / X-APPBRAND / X-Brand-Id."""

    name: str
    """Display name, used in the config flow and entry titles."""

    manufacturer: str
    """Device-registry manufacturer string."""

    auth_host: str
    """ForgeRock tenant hostname."""

    user_agent: str

    requires_account_bootstrap: bool
    """Whether GET v4/account must precede vehicle discovery.

    Subaru returns HTTP 200 with an empty payload from v2/vehicle/guid unless
    the account has been touched first -- apparently server-side session
    initialization specific to the Subaru flow.
    """

    @property
    def authenticate_url(self) -> str:
        return f"https://{self.auth_host}/json/{REALM_PATH}/authenticate"

    @property
    def authorize_url(self) -> str:
        return f"https://{self.auth_host}/oauth2/{REALM_PATH}/authorize"

    @property
    def access_token_url(self) -> str:
        return f"https://{self.auth_host}/oauth2/{REALM_PATH}/access_token"

    def headers(self) -> dict:
        """Brand-scoping headers required on gateway and GraphQL requests.

        X-APPBRAND is the one that gates vehicle discovery: without it, Subaru
        auth succeeds but the vehicle list comes back empty. X-Brand-Id is sent
        by the real app; whether the backend enforces it is unconfirmed, so it
        is included for parity.
        """
        return {
            "X-BRAND": self.code,
            "X-APPBRAND": self.code,
            "X-Brand-Id": self.code,
        }


TOYOTA = BrandConfig(
    code="T",
    name="Toyota",
    manufacturer="Toyota Motor North America",
    auth_host="login.toyotadriverslogin.com",
    user_agent=(
        "ToyotaOneApp/3.10.0 (com.toyota.oneapp; build:3100; Android 14) okhttp/4.12.0"
    ),
    requires_account_bootstrap=False,
)

SUBARU = BrandConfig(
    code="S",
    name="Subaru",
    manufacturer="Subaru of America",
    auth_host="login.subarudriverslogin.com",
    user_agent=(
        "SubaruConnect/3.10.0 (com.subaru.oneapp; build:3100; Android 14) okhttp/4.12.0"
    ),
    requires_account_bootstrap=True,
)

BRANDS = {brand.code: brand for brand in (TOYOTA, SUBARU)}

DEFAULT_BRAND = TOYOTA.code
"""Config entries created before brand support existed are Toyota."""


def get_brand(code) -> BrandConfig:
    """Resolve a brand code, falling back to Toyota for unknown or missing values.

    Falling back rather than raising keeps a corrupt or hand-edited config entry
    from taking down the whole integration at setup.
    """
    if isinstance(code, BrandConfig):
        return code
    return BRANDS.get(code, TOYOTA)
