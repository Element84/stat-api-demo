from anyio import sleep
from enum import Enum
from logging import getLogger
from os import getenv
from urllib.parse import urljoin
from typing import Literal

from geojson_pydantic import Point, Feature
from pydantic import BaseModel
from pystac import ProviderRole
from requests import Session, Request
from requests.auth import AuthBase
from requests.adapters import HTTPAdapter, Retry, BaseAdapter
from starlette import status
from stac_pydantic.links import Link

from api.models import Opportunity, Order, Product, Provider

"""
http \
    post \
    localhost:8000/opportunities \
    backend:satvu \
    Authorization:"Bearer ${TOKEN}" \
    geometry:='{"type": "Point", "coordinates": [12, 52]}' \
    product_id="standard-scene" datetime="2024-01-20T00:00:00/2024-02-29T00:00:00"
"""

SATVU_CONTRACT_ID_ENV = "SATVU_CONTRACT_ID"

logger = getLogger(__name__)


class FeasibilityRequestStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    failed = "failed"
    feasible = "feasible"
    not_feasible = "not feasible"


class StandardScene(Product):
    id = "standard-scene"
    title = "Standard scene"
    description = "Standard tasking product"
    license = "proprietary"
    links: list[Link] = (
        [
            Link(
                href="https://docs.satellitevu.com/guides/tasking/",
                title="Tasking guide",
                rel="docs",
                type="text/html",
            ),
        ],
    )
    providers: list[Provider] = [
        Provider(
            name="SatVu",
            description="",
            roles=[
                ProviderRole.LICENSOR,
                ProviderRole.PROCESSOR,
                ProviderRole.PRODUCER,
                ProviderRole.HOST,
            ],
            url="https://satellitevu.com",
        )
    ]


class RequestPayloadProperties(BaseModel):
    datetime: str


class RequestPayload(Feature[Point, RequestPayloadProperties]):
    type: Literal["Feature"]
    geometry: Point

    @classmethod
    def from_opportunity(cls, opportunity: Opportunity) -> "RequestPayload":
        if opportunity.geometry.type != "Point":
            raise RuntimeError("only POINT geometries are supported")

        return RequestPayload(
            type="Feature",
            geometry=opportunity.geometry,
            properties=RequestPayloadProperties(
                datetime=opportunity.datetime,
                **(opportunity.constraints or {}),
            ),
        )


class ResponsePayload(BaseModel):
    links: list[Link]


class BearerTokenAuth(AuthBase):
    token: str

    def __init__(self, token: str):
        self.token = token

    def __call__(self, request: Request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request


def new_session(token: str) -> Session:
    retries = Retry(
        total=5,
        backoff_factor=0.1,
        status_forcelist=[
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            status.HTTP_502_BAD_GATEWAY,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            status.HTTP_504_GATEWAY_TIMEOUT,
        ],
    )

    session = Session()
    session.auth = BearerTokenAuth(token)

    session.mount("http://", BaseAdapter)
    session.mount("https://", HTTPAdapter(max_retries=retries))

    return session


class SatVuBackend:
    BASE_URL = "https://api.qa.satellitevu.com/otm/v2/"
    _contract_id: str

    ASYNC_MAX_POLL_WAIT = 60
    ASYNC_POLL_WAIT = 0.5

    def __init__(self) -> None:
        self._contract_id = getenv(SATVU_CONTRACT_ID_ENV)

    async def find_products(
        self,
        token: str,
    ) -> list[Product]:
        """Get a list of all Products"""
        return [StandardScene]

    async def place_order(
        self,
        search: Opportunity,
        token: str,
    ) -> Order:
        """Given an Opportunity, place an order"""
        return NotImplemented

    async def find_opportunities(
        self,
        search: Opportunity,
        token: str,
    ) -> list[Opportunity]:
        """Given an Opportunity, get a list of Opportunites that fulfill it"""
        if not self._contract_id:
            raise RuntimeError(f"{SATVU_CONTRACT_ID_ENV} is not set.")

        session = new_session(token)

        try:
            # SatVu's OTM service is async, so...
            # 1. Send feasibility request...
            payload = RequestPayload.from_opportunity(search)
            url = urljoin(
                self.BASE_URL, f"./{self._contract_id}/tasking/feasibilities/"
            )
            data = payload.dict(exclude_unset=True)
            logger.debug(
                {
                    "message": "sending feasibility request",
                    "url": url,
                    "payload": data,
                }
            )

            res = session.post(url, json=data)
            res.raise_for_status()

            data = res.json()
            logger.debug(
                {
                    "message": "received feasibility request",
                    "status code": res.status_code,
                    "payload": data,
                }
            )
            item = ResponsePayload(**data)
            response_url = next(
                (link for link in item.links if link.rel == "self")
            ).href

            # 2. Poll feasibility request status...
            # SatVu's standard scene product opportunity is just a boolean basically
            for _ in range(int(self.ASYNC_MAX_POLL_WAIT / self.ASYNC_POLL_WAIT)):
                res = session.get(response_url)
                res.raise_for_status()
                data = res.json()
                logger.debug(
                    {
                        "message": "polling...",
                        "status code": res.status_code,
                        "payload": data,
                    }
                )

                status = data["properties"]["status"]
                match status:
                    case FeasibilityRequestStatus.feasible:
                        search.id = data["id"]
                        return [search]
                    case FeasibilityRequestStatus.not_feasible:
                        return []
                    case FeasibilityRequestStatus.failed:
                        raise RuntimeError("Opportunity request failed")
                await sleep(self.ASYNC_POLL_WAIT)
        except Exception as e:
            logger.exception(
                {
                    "message": "OTM request failed",
                }
            )
            raise e

        raise RuntimeError("Opportunity request timed out")
