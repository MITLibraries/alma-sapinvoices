import logging
import os

from boto3 import client

logger = logging.getLogger(__name__)


class SSM:
    """An SSM class that provides a generic boto3 SSM client.

    with specific SSM functionality necessary for sap invoices processing
    """

    def __init__(self) -> None:
        """Initialize SSM instance."""
        endpoint_from_env = os.getenv("SSM_ENDPOINT_URL")
        self.client = client(
            "ssm",
            region_name="us-east-1",
            endpoint_url=endpoint_from_env if endpoint_from_env else None,
        )
        logger.info(
            "Initializing SSM client with endpoint: %s", self.client.meta.endpoint_url
        )

    def get_parameter_history(self, parameter_key: str) -> list:
        """Get parameter history based on the specified key."""
        response = self.client.get_parameter_history(
            Name=parameter_key, WithDecryption=True
        )
        return response["Parameters"]

    def get_parameter_value(self, parameter_key: str) -> str:
        """Get parameter value based on the specified key."""
        parameter_object = self.client.get_parameter(
            Name=parameter_key, WithDecryption=True
        )
        return parameter_object["Parameter"]["Value"]

    def update_parameter_value(
        self, parameter_key: str, new_value: str, parameter_type: str
    ) -> dict:
        """Update parameter with specified value."""
        response = self.client.put_parameter(
            Name=parameter_key, Value=new_value, Type=parameter_type, Overwrite=True
        )
        logger.info(
            "SSM parameter '%s' was updated to '%s' with type=%s",
            parameter_key,
            new_value,
            parameter_type,
        )
        return response
