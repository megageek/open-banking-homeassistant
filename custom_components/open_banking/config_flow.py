from collections import OrderedDict
import hashlib

from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from custom_components.open_banking.ng import get_client
from . import DOMAIN, const

secret_id = None
secret_key = None


def sha1(msg: str) -> str:
    return hashlib.sha1(msg.encode()).hexdigest()


def valid_country(country):
    if str(country).upper() not in const["COUNTRIES"]:
        raise vol.Invalid("Unsuppored country specified")
    return str(country).upper()


def get_institutions(fn, country):
    def get():
        return fn(country)

    return get


def create_req(fn, **kwargs):
    def job():
        return fn(**kwargs)

    return job


class NordigenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    entry: config_entries.ConfigEntry

    _data = {}

    async def get_requisition(self, requisitions, institution_id, account_holder):
        reference = f"{account_holder}-{institution_id}"
        res = await self.hass.async_add_executor_job(requisitions.list)
        res = res.get("results", [])
        res = [
            requisition for requisition in res if requisition["reference"] == reference
        ]
        requisition = res[0] if len(res) > 0 else None

        if requisition and requisition["status"] in ["EX", "RJ", "SU"]:
            await self.hass.async_add_executor_job(
                requisitions.remove, requisition["id"]
            )
            requisition = None

        if requisition:
            return requisition

        return await self.hass.async_add_executor_job(
            create_req(
                requisitions.create,
                redirect="https://127.0.0.1",
                institution_id=institution_id,
                reference=reference,
            )
        )

    def _get_client(self, secret_id, secret_key):
        if secret_id and secret_key:
            return get_client(secret_id=secret_id, secret_key=secret_key)
        return None

    async def flow(self, user_input):
        errors = {}
        user_input = user_input or {}
        self._data.update(user_input)

        schema = OrderedDict()
        schema[
            vol.Required(
                const["ACCOUNT_HOLDER"], default=user_input.get(const["ACCOUNT_HOLDER"])
            )
        ] = cv.string
        schema[
            vol.Required(
                const["SECRET_ID"],
                default=user_input.get(const["SECRET_ID"], secret_id),
            )
        ] = cv.string
        schema[
            vol.Required(
                const["SECRET_KEY"],
                default=user_input.get(const["SECRET_KEY"], secret_key),
            )
        ] = cv.string

        country_field = const["COUNTRY_FIELD"]
        schema[vol.Required(country_field, default=user_input.get(country_field))] = (
            vol.In(const["COUNTRIES"])
        )

        client = self._get_client(
            secret_id=user_input.get(const["SECRET_ID"]),
            secret_key=user_input.get(const["SECRET_KEY"]),
        )

        if user_input.get(const["COUNTRY_FIELD"]) and client:
            try:
                institutions = await self.hass.async_add_executor_job(
                    client.institutions.by_country, user_input[const["COUNTRY_FIELD"]]
                )
                if not user_input.get(const["INSTITUTION_ID"]):
                    schema[
                        vol.Required(
                            const["INSTITUTION_ID"],
                            default=user_input.get(const["INSTITUTION_ID"]),
                        )
                    ] = vol.In([institution["id"] for institution in institutions])
            except Exception as exception:
                print("country exception", exception)
                errors["institution"] = str(exception)
                return (vol.Schema(schema), user_input, errors)

        if user_input.get(const["INSTITUTION_ID"]) and client:
            try:
                requisition = await self.get_requisition(
                    requisitions=client.requisitions,
                    institution_id=user_input[const["INSTITUTION_ID"]],
                    account_holder=user_input[const["ACCOUNT_HOLDER"]],
                )
                print("requisitions", requisition)
                if requisition["status"] != "LN":
                    info = f"Visit the link to activate the connection: {requisition['link']}"
                    errors["requisition"] = info

                    institutions = await self.hass.async_add_executor_job(
                        client.institutions.by_country,
                        user_input[const["COUNTRY_FIELD"]],
                    )
                    schema[
                        vol.Required(
                            const["INSTITUTION_ID"],
                            default=user_input.get(const["INSTITUTION_ID"]),
                            description=info,
                        )
                    ] = vol.In([inst["id"] for inst in institutions])

            except Exception as exception:
                print("requisition exception", exception)
                errors["requisition"] = str(exception)
                return (vol.Schema(schema), user_input, errors)

        return (vol.Schema(schema), user_input, errors)

    async def async_step_user(self, user_input=None):
        """This is the first step: collect secrets, institution, etc."""
        schema, user_input, errors = await self.flow(user_input or {})
        self._data.update(user_input)

        if user_input.get(const["INSTITUTION_ID"]):
            return await self.async_step_auth(user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_auth(self, user_input=None):
        """Second step: show the link, user must do the external flow, then confirm."""
        self._data.update(user_input or {})
        if user_input is None:
            return self.async_show_form(
                step_id="auth",
                data_schema=vol.Schema(
                    {
                        vol.Required("done", default=False): bool,
                    }
                ),
                description_placeholders={},
                errors={},
            )

        if user_input.get("done"):
            client = self._get_client(
                secret_id=self._data[const["SECRET_ID"]],
                secret_key=self._data[const["SECRET_KEY"]],
            )

            try:
                requisition = await self.get_requisition(
                    requisitions=client.requisitions,
                    institution_id=self._data[const["INSTITUTION_ID"]],
                    account_holder=self._data[const["ACCOUNT_HOLDER"]],
                )

                if requisition["status"] == "LN":
                    return self.async_create_entry(
                        title=f"Open Banking ({const['ACCOUNT_HOLDER']} :: {const['INSTITUTION_ID']})",
                        data={
                            **self._data,
                            "enduser_id": sha1(
                                f"{self._data[const['INSTITUTION_ID']]}-{self._data[const['SECRET_ID']]}-{self._data[const['ACCOUNT_HOLDER']]}"
                            ),
                        },
                    )
                else:
                    return self.async_show_form(
                        step_id="auth",
                        data_schema=vol.Schema(
                            {
                                vol.Required("done", default=False): bool,
                            }
                        ),
                        errors={"base": "authorization_not_complete"},
                    )
            except Exception as err:
                return self.async_show_form(
                    step_id="auth",
                    data_schema=vol.Schema(
                        {
                            vol.Required("done", default=False): bool,
                        }
                    ),
                    errors={"base": str(err)},
                )

        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema(
                {
                    vol.Required("done", default=False): bool,
                }
            ),
            errors={},
        )
