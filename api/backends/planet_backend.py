import os
import time

import requests
from api.models import Opportunity, Product, Provider

PLANET_BASE_URL = "https://api.staging.planet-labs.com"


def search_to_imaging_window_request(search_request: Opportunity) -> dict:
    """
    :param search: search object as passed on to find_opportunities
    :return: a corresponding request to retrieve imaging windows
    """

    # pl_number and pl_product would need to always be provided in a prod setting,
    # providing defaults here only temporarily
    pl_number, pl_product = "PL-QA", "Assured Tasking"
    if search_request.product_id:
        pl_number, pl_product = search_request.product_id.split(":")

    return {
        "datetime": f"{search_request.start_date.isoformat()}/{search_request.end_date.isoformat()}",
        "pl_number": pl_number,
        "product": pl_product,
        "geometry": search_request.geometry.dict(),
    }


def get_imaging_windows(planet_request, token: str) -> list:
    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "authorization": token,
    }

    r = requests.post(
        f"{PLANET_BASE_URL}/tasking/v2/imaging-windows/search",
        headers=headers,
        json=planet_request,
    )

    if "location" not in r.headers:
        raise ValueError(
            "Header 'location' not found: %s, status %s, body %s"
            % (list(r.headers.keys()), r.status_code, r.text)
        )

    poll_url = f"{PLANET_BASE_URL}{r.headers['location']}"
    os.environ["PLANET_LAST_POLL_URL"] = poll_url

    while True:
        r = requests.get(poll_url, headers=headers)
        status = r.json()["status"]
        if status == "DONE":
            return r.json()["imaging_windows"]
        elif status == "FAILED":
            raise ValueError(
                f"Retrieving Imaging Windows failed: {r.json()['error_code']} - {r.json()['error_message']}'"
            )
        # todo async
        time.sleep(1)


def imaging_window_to_opportunity(iw, geom, search_request) -> Opportunity:
    """
    translates a Planet Imaging Window into an Opportunity
    :param iw: an element from the 'imaging_windows' array of a /imaging_windows/[search_id] response
    :return: a corresponding opportunity
    """

    return Opportunity(
        id=iw["id"],
        geometry=geom,
        datetime=f"{iw['start_time']}/{iw['end_time']}",
        product_id=search_request.product_id,
        constraints={
            "off_nadir": [iw["start_off_nadir"], iw["end_off_nadir"]],
            "cloud_cover": iw["cloud_forecast"][0]["prediction"],
        },
    )


class PlanetBackend:
    async def find_opportunities(
        self,
        search_request: Opportunity,
        token: str,
    ) -> list[Opportunity]:
        # this assumes we have an Assured product i.e. one which is ordered with respect to a
        # specific imaging window
        # todo: extend this flow to flexible orders

        planet_request = search_to_imaging_window_request(search_request)
        imaging_windows = get_imaging_windows(planet_request, token)
        opportunities = [
            imaging_window_to_opportunity(
                iw, planet_request["geometry"], search_request
            )
            for iw in imaging_windows
        ]
        # todo: combine original request and returned imaging window such that the returned
        #   opportunities are a valid order structure

        return opportunities

    async def find_products(self, token: str) -> list[Product]:
        # todo: get real list of products
        # todo: consider proper reactions for all types of products (i.e. non-assured)
        return [
            Product(
                type="Product",
                stat_version="0.0.1",
                stat_extensions=[],
                id="PL-QA:Assured Tasking",
                title="Assured Tasking",
                description="",
                license="",
                links=[],
                keywords=[],
                providers=[Provider(name="planet")],
                constraints={},
                parameters={},
            )
        ]
