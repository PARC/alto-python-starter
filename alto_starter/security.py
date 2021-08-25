from pydantic import BaseModel
from typing import List
from keycloak import KeycloakOpenID

from fastapi import Request
from fastapi.security.utils import get_authorization_scheme_param
from fastapi.responses import JSONResponse

from jose import JWTError


class User(BaseModel):
    roles: List[str]
    scope: List[str]
    client_id: str
    client_host: str
    organization: str
    project: str


class Security:
    def __init__(self, service, props):
        self.keycloak_openid = KeycloakOpenID(server_url=props.url,
                                              client_id=service,
                                              realm_name=props.realm or "master",
                                              verify=True,
                                              client_secret_key=props.client_secret,
                                              custom_headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.public_key = "-----BEGIN PUBLIC KEY-----\n{}\n-----END PUBLIC KEY-----".format(
            self.keycloak_openid.public_key())
        self._service = service

    async def middleware(self, request: Request, call_next):
        if request.url.path == '/actuator/health':
            return await call_next(request)
        auth_header = request.headers.get("Authorization")
        scheme, credentials = get_authorization_scheme_param(auth_header)
        if not auth_header or scheme.lower() != "bearer":
            return JSONResponse(status_code=401)
        # TODO user introspect in case to check whether client is enable or not (it tooks 100ms)
        # token_info = self.keycloak_openid.introspect(credentials)
        # options = {"verify_signature": True, "verify_aud": True, "verify_exp": True}
        try:
            options = {"verify_signature": True, "verify_aud": False, "verify_exp": True}
            decode = self.keycloak_openid.decode_token(credentials, key=self.public_key, options=options)
            roles = decode.get("resource_access").get(self._service).get("roles")
            client_id = decode.get("clientId")
            client_host = decode.get("clientHost")
            scope = decode.get("scope").split(" ")
            organization = decode.get("organization", None)
            project = decode.get("project", None)
            user = User(client_id=client_id, client_host=client_host, scope=scope, roles=roles, project=project,
                        organization=organization)

            # TODO temp client
            # user.project = "project_a"
            # user.organization = "first_company"

            request.state.user = user
            return await call_next(request)
        except JWTError as ex:
            return JSONResponse(status_code=401)
        pass


def get_current_user(request: Request):
    return request.state.user
