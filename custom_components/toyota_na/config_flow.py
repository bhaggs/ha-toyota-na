import logging

from homeassistant import config_entries
import voluptuous as vol

from toyota_na.exceptions import AuthError

from .const import BRAND, DOMAIN
from .oneapi import BRANDS, DEFAULT_BRAND, OneAuth, OneClient, get_brand

_LOGGER = logging.getLogger(__name__)

BRAND_CHOICES = {code: brand.name for code, brand in BRANDS.items()}


class ToyotaNAConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Toyota and Subaru North America connected services"""

    _default_brand = DEFAULT_BRAND

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self.user_info = user_input
                # Brand is fixed at construction: it selects the login tenant,
                # so it must be right before the first request goes out.
                self.client = OneClient(
                    OneAuth(brand=user_input.get(BRAND, DEFAULT_BRAND))
                )
                await self.client.auth.authorize(
                    user_input["username"], user_input["password"]
                )
                return await self.async_step_otp()
            except AuthError:
                errors["base"] = "not_logged_in"
                _LOGGER.error("Not logged in with username and password")
            except Exception:
                errors["base"] = "unknown"
                _LOGGER.exception("Unknown error with username and password")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(BRAND, default=self._default_brand): vol.In(
                        BRAND_CHOICES
                    ),
                    vol.Required("username"): str,
                    vol.Required("password"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_otp(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self.otp_info = user_input
                data = await self.async_get_entry_data(self.client, errors)
                if data:
                    return await self.async_create_or_update_entry(data=data)
            except AuthError:
                errors["base"] = "not_logged_in"
                _LOGGER.error("Not logged in with one time password")
            except Exception as e:
                errors["base"] = "unknown"
                _LOGGER.exception("Unknown error with one time password")
        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema(
                {vol.Required("code"): str}
            ),
            errors=errors,
        )

    async def async_get_entry_data(self, client, errors):
        try:
            await client.auth.login(self.user_info["username"], self.user_info["password"], self.otp_info["code"])
            id_info = await client.auth.get_id_info()

            # The OAuth scope is "openid profile write" - no email scope - so an
            # email claim is whatever the tenant chooses to include. Toyota's
            # returns one; do not assume Subaru's does. Fall back to the subject
            # (the account GUID), which is always present and is all this value
            # has to be: stable and unique per account.
            account_id = id_info.get("email") or id_info.get("sub")
            if not account_id:
                _LOGGER.error(
                    "Token had neither an email nor a sub claim; claims present: %s",
                    sorted(id_info),
                )
                errors["base"] = "unknown"
                return None
            if not id_info.get("email"):
                _LOGGER.debug(
                    "No email claim from %s; identifying account by sub instead",
                    client.brand.name,
                )

            return {
                BRAND: client.brand.code,
                "tokens": client.auth.get_tokens(),
                "email": account_id,
                "username": self.user_info["username"],
                "password": self.user_info["password"],
            }
        except AuthError:
            errors["base"] = "otp_not_logged_in"
            _LOGGER.error("Invalid Verification Code")
        except Exception:
            errors["base"] = "unknown"
            _LOGGER.exception("Unknown error setting up %s account", client.brand.name)

    @staticmethod
    def _unique_id(data):
        """Namespace by brand so one email can hold both a Toyota and a Subaru entry.

        Toyota keeps the original un-prefixed form so existing entries keep
        their identity across the upgrade and are not orphaned.
        """
        brand = get_brand(data.get(BRAND))
        if brand.code == DEFAULT_BRAND:
            return f"{DOMAIN}:{data['email']}"
        return f"{DOMAIN}:{brand.code}:{data['email']}"

    async def async_create_or_update_entry(self, data):
        existing_entry = await self.async_set_unique_id(self._unique_id(data))
        if existing_entry:
            self.hass.config_entries.async_update_entry(existing_entry, data=data)
            await self.hass.config_entries.async_reload(existing_entry.entry_id)
            return self.async_abort(reason="reauth_successful")
        brand = get_brand(data.get(BRAND))
        return self.async_create_entry(
            title=f"{brand.name} - {data['email']}", data=data
        )

    async def async_step_reauth(self, data):
        # Default the form to the brand already on the entry, so reauth cannot
        # silently move an entry to the wrong login tenant.
        if data:
            self._default_brand = get_brand(data.get(BRAND)).code
        return await self.async_step_user()
