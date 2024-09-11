# imports
from typing import Dict
import pathlib
from io import BytesIO
import pandas as pd
from pydantic import PrivateAttr
import girder_client
from dagster import ConfigurableResource


class IMQCAMGirderResource(ConfigurableResource):
    """A Connection to the IMQCAM Girder instance as a Dagster Resource. Configurable
    parameters are "api_url" and "api_key".
    """

    ############################## CONFIGURABLE PARAMETERS ##############################

    api_url: str
    api_key: str

    _client: girder_client.GirderClient = PrivateAttr()

    ################################# PUBLIC FUNCTIONS #################################

    def setup_for_execution(self, context) -> None:  # pylint: disable=unused-argument
        self._client = girder_client.GirderClient(apiUrl=self.api_url)

    def get_folder_file_names_and_ids(self, girder_folder_path: str) -> Dict[str, str]:
        """Return a dictionary of file IDs keyed by filename for all files inside the given
        folder path on Girder. Only returns entries for files directly inside the given
        folder, not any files nested further in subdirectories.

        Args:
            girder_folder_path (str): The path to the folder in Girder as a string
                formatted like [collection_name]/path/to/folder

        Returns:
            Dict[str: str]: A dictionary of file IDs keyed by their names for files
                directly inside girder_folder_path (not nested further in subfolders)
        """
        # parse the folder path to get the collection name, and relative path to the folder
        collection_name, rel_folder_path = self._get_collection_name_and_rel_path(
            girder_folder_path
        )
        folder_id = self._get_folder_id(
            rel_folder_path, collection_name=collection_name
        )
        file_names_ids = {}
        for item_resp in self._client.listItem(folder_id):
            for file_resp in self._client.listFile(item_resp["_id"]):
                file_names_ids[file_resp["name"]] = file_resp["_id"]
        return file_names_ids

    def get_dataframe_from_girder_csv_file(self, girder_file_path: str) -> pd.DataFrame:
        """Read the file at girder_file_path as a CSV and return its contents
        as a pandas dataframe

        Args:
            girder_file_path (str): The path to the file in Girder as a string formatted
                like [collection_name]/path/to/file.csv

        Returns:
            pandas.DataFrame: The contents of the file read into a pandas dataframe
        """
        # get the file ID for the file
        collection_name, rel_file_path = self._get_collection_name_and_rel_path(
            girder_file_path
        )
        file_id = self._get_file_id(rel_file_path, collection_name=collection_name)
        # read the file contents into a bytestring
        file_contents = self._client.downloadFileAsIterator(file_id)
        file_data = b"".join(chunk for chunk in file_contents)
        # make the file into a DataFrame and return it
        df = pd.read_csv(BytesIO(file_data))
        return df

    def write_dataframe_to_girder_file(
        self, dataframe: pd.DataFrame, girder_file_path: str, **to_csv_kwargs: dict
    ) -> str:
        """Write the given dataframe to a csv file stored in Girder at the given path.
        Any folders in the file path structure that don't already exist will be created
        as public Folders.

        Args:
            dataframe (pandas.DataFrame): the dataframe object to write out to a file
            girder_file_path (str): The path to the file in Girder to write to as a
                string formatted like [collection_name]/path/to/file.csv
            to_csv_kwargs (dict): a dictionary of kwargs to pass to the dataframe.to_csv
                call
        """
        # parse the filepath to get the collection name, and relative path to the file
        path_split = girder_file_path.split("/")
        collection_name = path_split[0]
        rel_parent_folder_path = "/".join(path_split[1:-1])
        # get the ID of the folder that the new file should be added to
        upload_folder_id = self._get_folder_id(
            rel_parent_folder_path,
            collection_name=collection_name,
            create_if_not_found=True,
        )
        # upload the content to the folder
        buffer = BytesIO()
        dataframe.to_csv(buffer, **to_csv_kwargs)
        bytestring = buffer.getvalue()
        self._client.uploadFile(
            upload_folder_id,
            BytesIO(bytestring),
            path_split[-1],
            len(bytestring),
            "folder",
        )

    ############################# PRIVATE HELPER FUNCTIONS #############################

    def _get_collection_name_and_rel_path(self, girder_path):
        # parse the path to get the collection name and relative path to the file
        path_split = girder_path.split("/")
        if len(path_split) < 2:
            raise ValueError(
                (
                    f"ERROR: girder path {girder_path} does not have enough parts "
                    "to specify a file or folder within a collection!"
                )
            )
        collection_name = path_split[0]
        rel_file_path = "/".join(path_split[1:])
        return collection_name, rel_file_path

    def _login(self):
        """Authenticate the client if it isn't already authenticated"""
        # If the token is set we don't need to re-authenticate
        if self._client.token is not None and self._client.token != "":
            return
        try:
            self._client.authenticate(apiKey=self.api_key)
        except Exception as exc:
            raise ValueError(
                f"ERROR: failed to authenticate to Girder at {self.api_url}!"
            ) from exc

    def _get_folder_id(
        self,
        folder_rel_path,
        root_folder_id=None,
        collection_name=None,
        create_if_not_found=False,
        create_as_public=True,
    ):
        """Return the ID of a particular Girder Folder located at folder_rel_path
        relative to a given root_folder_id or collection_name. If create_if_not_found
        is True the Folder will be created with its nested structure if it doesn't
        already exist. If create_as_public is additionally True (the default) any created
        Folders will be public.
        """
        if (root_folder_id is not None and collection_name is not None) or (
            root_folder_id is None and collection_name is None
        ):
            raise ValueError(
                "Must specify exactly one of root_folder_id or collection_name"
            )
        if isinstance(folder_rel_path, str):
            folder_rel_path = pathlib.Path(folder_rel_path)
        self._login()
        if root_folder_id is not None:
            current_folder_id = root_folder_id
            init_pftype = "folder"
        else:
            collection_id = None
            for resp in self._client.listCollection():
                if (
                    resp["_modelType"] == "collection"
                    and resp["name"] == collection_name
                ):
                    collection_id = resp["_id"]
            if collection_id is None:
                raise ValueError(
                    f"Failed to find a Girder Collection called {collection_name}!"
                )
            current_folder_id = collection_id
            init_pftype = "collection"
        for idepth, folder_name in enumerate(folder_rel_path.parts):
            pftype = init_pftype if idepth == 0 else "folder"
            found = False
            for resp in self._client.listFolder(
                current_folder_id, parentFolderType=pftype, name=folder_name
            ):
                found = True
                current_folder_id = resp["_id"]
            if not found:
                if create_if_not_found:
                    current_folder_id = self._client.createFolder(
                        current_folder_id,
                        folder_name,
                        parentType=pftype,
                        public=create_as_public,
                    )["_id"]
                else:
                    raise ValueError(
                        (
                            "ERROR: failed to find the Girder Folder "
                            f"{'/'.join(folder_rel_path.parts[:idepth+1])} in the "
                            f"{collection_name} Collection!"
                        )
                    )
        return current_folder_id

    def _get_item_id(self, item_rel_path, root_folder_id=None, collection_name=None):
        """Return the ID of a particular Girder Item located at item_rel_path relative to
        a particular root_folder_id or collection_name.
        """
        if isinstance(item_rel_path, str):
            item_rel_path = pathlib.Path(item_rel_path)
        folder_id = self._get_folder_id(
            item_rel_path.parent,
            root_folder_id=root_folder_id,
            collection_name=collection_name,
        )
        item_id = None
        for resp in self._client.listItem(folder_id, name=item_rel_path.name):
            item_id = resp["_id"]
        if item_id is None:
            errmsg = (
                f"Failed to find an Item called {item_rel_path.name} in "
                f"{collection_name}/{item_rel_path.parent}"
            )
            raise ValueError(errmsg)
        return item_id

    def _get_file_id(self, file_rel_path, root_folder_id=None, collection_name=None):
        """Return the ID of a particular Girder File (inside an Item with the same name)
        located at file_rel_path relative to a given root_folder_id or collection_name.
        """
        item_id = self._get_item_id(
            file_rel_path,
            root_folder_id=root_folder_id,
            collection_name=collection_name,
        )
        for resp in self._client.listFile(item_id):
            file_id = resp["_id"]
        return file_id
