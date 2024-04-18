# imports
from io import BytesIO
import pandas as pd
from .utilities import (
    get_authenticated_girder_client,
    get_girder_folder_id,
    get_girder_item_and_file_id,
)


def get_dataframe_from_girder_csv_file(girder_file_path: str) -> pd.DataFrame:
    # get an authenticated girder client to use
    client = get_authenticated_girder_client()
    # parse the filepath to get the collection name, and relative path to the file
    path_split = girder_file_path.split("/")
    collection_name = path_split[0]
    rel_file_path = "/".join(path_split[1:])
    # get the item and file ID for the file
    _, file_id = get_girder_item_and_file_id(
        client, rel_file_path, collection_name=collection_name
    )
    # read the file contents into a bytestring
    file_contents = client.downloadFileAsIterator(file_id)
    file_data = b"".join(chunk for chunk in file_contents)
    # make the file into a DataFrame and return it
    df = pd.read_csv(BytesIO(file_data))
    return df


def write_dataframe_to_girder_file(girder_file_path: str, dataframe: bytes) -> str:
    # get an authenticated girder client to use
    client = get_authenticated_girder_client()
    # parse the filepath to get the collection name, and relative path to the file
    path_split = girder_file_path.split("/")
    collection_name = path_split[0]
    rel_parent_folder_path = "/".join(path_split[1:-1])
    # get the ID of the folder that the new file should be added to
    upload_folder_id = get_girder_folder_id(
        client,
        rel_parent_folder_path,
        collection_name=collection_name,
        create_if_not_found=True,
    )
    # upload the content to the folder
    buffer = BytesIO()
    dataframe.to_csv(buffer, index=False)
    bytestring = buffer.getvalue()
    client.uploadFile(
        upload_folder_id,
        BytesIO(bytestring),
        path_split[-1],
        len(bytestring),
        "folder",
    )
    # return the string path to the new file
    return girder_file_path
