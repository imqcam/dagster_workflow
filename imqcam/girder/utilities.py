# imports
import os
import pathlib
import girder_client

def get_authenticated_girder_client():
    # read girder-related env vars
    api_url = os.getenv("GIRDER_API_URL")
    if api_url is None:
        raise RuntimeError("ERROR: no value set for 'GIRDER_API_URL' env var!")
    api_key = os.getenv("GIRDER_API_KEY")
    if api_key is None:
        raise RuntimeError("ERROR: no value set for 'GIRDER_API_KEY' env var!")
    # Authenticate to the Girder instance
    try:
        client = girder_client.GirderClient(apiUrl=api_url)
        client.authenticate(apiKey=api_key)
    except Exception as exc:
        raise ValueError(f"ERROR: failed to authenticate to Girder at {api_url}!") from exc
    # return the authenticated client
    return client

def get_girder_folder_id(
    client,
    folder_rel_path,
    root_folder_id=None,
    collection_name=None,
    create_if_not_found=False,
    create_as_public=True,
):
    """Return the ID of a particular Girder Folder.

    Args:
        client (girder_client.GirderClient): The Girder client to use
        folder_rel_path (pathlib.Path or str): The path to the desired folder, relative
            to some root location determined by other arguments
        root_folder_id (str, optional): ID of the folder that "folder_rel_path" is
            relative to. Either this OR "collection_name" must be given.
        collection_name (str, optional): Name of the Collection that "folder_rel_path"
            is relative to. Either this OR "root_folder_id" must be given.
        create_if_not_found (bool, optional): If True, any missing Folders in the path to
            the desired Folder will be created
        create_as_public (bool, optional): If True, any created Folders will be public

    Returns:
        str: ID of the Girder Folder located at
            [root_folder_id OR collection_name]/folder_rel_path

    Raises:
        ValueError: If both or neither of "root_folder_id" and "collection_name" are
            given (exactly one of them is required)
        ValueError: If the desired Folder or any of its parents don't exist and
            "create_if_not_found" is False
    """
    if (root_folder_id is not None and collection_name is not None) or (
        root_folder_id is None and collection_name is None
    ):
        raise ValueError(
            "Must specify exactly one of root_folder_id or collection_name"
        )
    if isinstance(folder_rel_path, str):
        folder_rel_path = pathlib.Path(folder_rel_path)
    if root_folder_id is not None:
        current_folder_id = root_folder_id
        init_pftype = "folder"
    else:
        collection_id = None
        for resp in client.listCollection():
            if resp["_modelType"] == "collection" and resp["name"] == collection_name:
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
        for resp in client.listFolder(
            current_folder_id, parentFolderType=pftype, name=folder_name
        ):
            found = True
            current_folder_id = resp["_id"]
        if not found:
            if create_if_not_found:
                current_folder_id = client.createFolder(
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


def get_girder_item_id(
    client, item_rel_path, root_folder_id=None, collection_name=None
):
    """Return the ID of a particular Girder Item.

    Args:
        client (girder_client.GirderClient): The Girder client to use
        item_rel_path (pathlib.Path or str): The path to the desired Item, relative
            to some root location determined by other arguments
        root_folder_id (str, optional): ID of the folder that "item_rel_path" is
            relative to. Either this OR "collection_name" must be given.
        collection_name (str, optional): Name of the Collection that "item_rel_path"
            is relative to. Either this OR "root_folder_id" must be given.

    Returns:
        str: The ID of the specified Girder item

    Raises:
        ValueError: if not exactly one of "root_folder_id" and "collection_name" are given
        ValueError: if the Item can't be found at the given path
    """
    if isinstance(item_rel_path, str):
        item_rel_path = pathlib.Path(item_rel_path)
    folder_id = get_girder_folder_id(
        client,
        item_rel_path.parent,
        root_folder_id=root_folder_id,
        collection_name=collection_name,
    )
    item_id = None
    for resp in client.listItem(folder_id, name=item_rel_path.name):
        item_id = resp["_id"]
    if item_id is None:
        errmsg = (
            f"Failed to find an Item called {item_rel_path.name} in "
            f"{collection_name}/{item_rel_path.parent}"
        )
        raise ValueError(errmsg)
    return item_id


def get_girder_item_and_file_id(
    client, file_rel_path, root_folder_id=None, collection_name=None
):
    """Return the IDs of a particular Girder File and its Item with the same name.

    Args:
        client (girder_client.GirderClient): The Girder client to use
        file_rel_path (pathlib.Path or str): The path to the desired File, relative
            to some root location determined by other arguments
        root_folder_id (str, optional): ID of the folder that "file_rel_path" is
            relative to. Either this OR "collection_name" must be given.
        collection_name (str, optional): Name of the Collection that "file_rel_path"
            is relative to. Either this OR "root_folder_id" must be given.

    Returns:
        tuple(str, str): The ID of the specified Girder Item and File, in that order

    Raises:
        ValueError: if not exactly one of "root_folder_id" and "collection_name" are given
        ValueError: if the Item can't be found at the given path
    """
    item_id = get_girder_item_id(
        client,
        file_rel_path,
        root_folder_id=root_folder_id,
        collection_name=collection_name,
    )
    for resp in client.listFile(item_id):
        file_id = resp["_id"]
    return item_id, file_id
