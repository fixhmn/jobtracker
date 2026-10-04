import httpx


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0):
        self.status = status
        super().__init__(message)


class ApiClient:
    def __init__(self, base_url: str, api_key: str, *, transport=None):
        self.client = httpx.AsyncClient(
            base_url=base_url, headers={"X-API-Key": api_key}, timeout=10, transport=transport
        )

    async def close(self):
        await self.client.aclose()

    async def export_csv(self, status=None):
        params = {"status": status} if status else {}
        try:
            response = await self.client.get("/applications/export.csv", params=params)
        except httpx.RequestError as error:
            raise ApiError("Can't reach JobTracker right now. Try again in a moment.") from error
        if response.status_code == 413:
            raise ApiError(
                "There are too many jobs for one export. Use /export Applied to filter.", 413
            )
        if response.is_error:
            raise ApiError(
                "Couldn't export the jobs. Check the API connection and key.", response.status_code
            )
        return response.content

    async def request(self, method: str, path: str, **kwargs):
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.RequestError as error:
            raise ApiError("Can't reach JobTracker right now. Try again in a moment.") from error
        if response.is_error:
            messages = {
                401: "The API key isn't configured correctly. Check .env.",
                404: "That record doesn't exist. Check its number with /list.",
                409: "That action conflicts with an existing record.",
                422: "Some details aren't valid. Check your input and try again.",
                503: "The database is busy. Try again in a moment.",
            }
            message = messages.get(response.status_code, "JobTracker couldn't finish that request.")
            if response.status_code == 409:
                detail = response.json().get("detail")
                if isinstance(detail, dict) and detail.get("application_id"):
                    message = f"You already saved this job. Use /view {detail['application_id']}."
            raise ApiError(message, response.status_code)
        return response.json()
