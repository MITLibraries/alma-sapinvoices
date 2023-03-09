from io import BytesIO, StringIO

import fabric


class SFTP:
    """An SFTP class with functionality for connecting to a host and sending files."""

    def __init__(self) -> None:
        """Initizliaze SFTP instance."""
        self.client = fabric.SSHClient()

    def authenticate(
        self, host: str, port: int, username: str, private_key: str
    ) -> None:
        """Authenticate the client to an SFTP host."""
        self.client.set_missing_host_key_policy(fabric.AutoAddPolicy())
        pkey = fabric.RSAKey.from_private_key(StringIO(private_key))
        self.client.connect(
            hostname=host,
            port=port,
            username=username,
            look_for_keys=False,
            pkey=pkey,
            disabled_algorithms={"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
        )

    def send_file(self, file_contents: str, file_path: str):
        """Send the string contents of a file to specified path on the SFTP server.

        The file_path parameter should include the path and file name e.g.
        "path/to/file.txt", if no path is included the file will be sent to the home
        folder for the SFTP user. Note that any directories included in the path MUST
        already exist on the server.

        Returns: SFTPAttributes object containing attributes of sent file on the server
        """
        return fabric.Connection.put(
            BytesIO(bytes(file_contents, encoding="utf-8")), file_path
        )
