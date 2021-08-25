import os
import boto3
import json
import socket

import py_eureka_client.eureka_client as eureka_client
from starlette.middleware.base import BaseHTTPMiddleware

from .healthcheck import router as hc_router
from .security import Security


class Props(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def from_dict(cls, params):
        res = Props()
        for k, v in params.items():
            if '.' in k:
                root, subkey = k.split(".", 1)
                if root in res and type(res[root]) is Props:
                    res[root] += Props.from_value(subkey, v)
                else:
                    res[root] = Props.from_value(subkey, v)
            else:
                if k in res and type(res[k]) is Props:
                    res[k]._value = v
                else:
                    res[k] = v
        return res

    @classmethod
    def from_value(cls, key, value):
        return Props.from_dict({key: value})

    def __setattr__(self, key, value):
        if type(value) is dict:
            self[key] = Props.from_dict(value)
        else:
            self[key] = value

    def __getattr__(self, item):
        return self.get(item, None)

    def __iter__(self):
        for k, v in self.items():
            yield k, v

    def to_dict(self):
        return {k: (v.to_dict() if type(v) is Props else v) for k, v in self}

    def __add__(self, other):
        if not other:
            return self
        if type(other) is Props:
            for k, v in other:
                if k in self and type(self[k]) is Props:
                    self[k] += v
                else:
                    self[k] = v
        else:
            self._value = other
        return self

    def pop(self, k, default=None):
        res = self.__getattr__(k)
        if res:
            self.__delitem__(k)
            return res
        else:
            if type(default) is dict:
                return Props.from_dict(default)
            return default


props = Props()

def alto_app(fast_api):
    _service = os.getenv("SERVICE", "intelligent-search")
    _environment = os.getenv("ENVIRONMENT", "local")
    _deployment = os.getenv("DEPLOYMENT", "local")
    _region = os.getenv('AWS_REGION', 'us-east-1')

    def ssm_params_dict():
        session = boto3.Session(region_name=_region).client("ssm")
        path = f'/alto/{_service}_{_deployment}'
        response = session.get_parameters_by_path(
            Path=path,
            Recursive=True,
            WithDecryption=True
        )

        params = response["Parameters"]
        while response.get("NextToken"):
            response = session.get_parameters_by_path(
                Path=path,
                Recursive=True,
                WithDecryption=True,
                NextToken=response["NextToken"]
            )
            params += response["Parameters"]

        return {item['Name'].replace(path + "/", ""): item['Value'] for item in params}

    def local_params_dict():
        res = None
        with open('./local.config') as f:
            res = json.load(f)
            f.close()
        return res

    def init_eureka(eureka_props):
        eureka_client.init(eureka_server=eureka_props.url if eureka_props and eureka_props.url else f"http://registry.{_deployment}.svc.cluster.local",
                           app_name=_service,
                           instance_port=eureka_props.port if eureka_props and eureka_props.port else 8080,
                           eureka_context=eureka_props.context if eureka_props and eureka_props.context else "/eureka",
                           instance_ip=eureka_props.server_ip if eureka_props and eureka_props.server_ip else socket.gethostbyname(socket.gethostname()),
                           instance_host=eureka_props.server_ip if eureka_props and eureka_props.server_ip else socket.gethostbyname(socket.gethostname()))

    def wrap(func):
        global props

        params = ssm_params_dict() if _environment != "local" else local_params_dict()
        print("Params: " + str(params))
        props += Props.from_dict(params)

        sys_props = props.pop('sys', {})
        init_eureka(sys_props.eureka)
        fast_api.include_router(hc_router, prefix="/actuator/health", tags=["Health check"])
        security = Security(_service, sys_props.keycloak)
        fast_api.add_middleware(BaseHTTPMiddleware, dispatch=security.middleware)

        return func

    return wrap