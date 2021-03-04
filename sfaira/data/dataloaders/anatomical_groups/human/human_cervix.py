from typing import Union

from sfaira.data import DatasetGroup
from sfaira.data.dataloaders.super_group import DatasetSuperGroupSfaira


class DatasetGroupCervix(DatasetGroup):

    def __init__(
        self,
        data_path: Union[str, None] = None,
        meta_path: Union[str, None] = None,
        cache_path: Union[str, None] = None
    ):
        dsg = DatasetSuperGroupSfaira(data_path=data_path, meta_path=meta_path, cache_path=cache_path)
        dsg.subset(key="id", values=[
            "human_cervix_2020_microwell_han_001_10.1038/s41586-020-2157-4"
        ])
        super().__init__(datasets=dsg.flatten().datasets)
