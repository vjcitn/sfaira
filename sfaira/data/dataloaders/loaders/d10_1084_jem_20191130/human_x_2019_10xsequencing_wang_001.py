import anndata
import os
import numpy as np
import scipy.sparse

from sfaira.data import DatasetBase

SAMPLE_FNS = [
    "wang20_colon.processed.h5ad",
    "wang20_ileum.processed.h5ad",
    "wang20_rectum.processed.h5ad"
]


class Dataset(DatasetBase):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.download_url_data = f"https://covid19.cog.sanger.ac.uk/{self.sample_fn}"
        self.download_url_meta = None

        organ = self.sample_fn.split("_")[1].split(".")[0]

        self.author = "Wang"
        self.doi = "10.1084/jem.20191130"
        self.healthy = True
        self.normalization = "raw"
        self.organ = organ
        self.organism = "human"
        self.protocol = "10X sequencing"
        self.state_exact = "healthy"
        self.year = 2019

        self.var_symbol_col = "index"
        self.cellontology_original_obs_key = "CellType"

        self.set_dataset_id(idx=1)


def load(data_dir, sample_fn, **kwargs):
    fn = os.path.join(data_dir, sample_fn)
    adata = anndata.read(fn)
    adata.X = np.expm1(adata.X)
    adata.X = adata.X.multiply(scipy.sparse.csc_matrix(adata.obs["n_counts"].values[:, None])).multiply(1 / 10000)

    return adata
