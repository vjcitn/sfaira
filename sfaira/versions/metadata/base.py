import abc
import networkx
import numpy as np
import obonet
import os
import pickle
import requests
from typing import Dict, List, Tuple, Union

FILE_PATH = __file__

"""
Ontology managament classes.

We consider any structured collection of meta data identifiers an ontology and define classes to interact with such
data here.

- All classes inherit from Ontology()
- Onotlogies can be read as follows:
    - from string lists which are typically hardcoded in sfaira (OntologyList),
    - from .obo files which are emitted by obofoundry for example (OntologyObo)),
    - ToDo from .owl files which are emitted from EBI for example (OntologyOwl)),
    - from the EBI web API via direct queries (OntologyEbi)).

ToDo explain usage of ontology extension.
"""


def get_base_ontology_cache() -> str:
    folder = FILE_PATH.split(os.sep)[:-4]
    folder.insert(1, os.sep)
    return os.path.join(*folder, "cache", "ontologies")


def cached_load_obo(url, ontology_cache_dir, ontology_cache_fn):
    if os.name == "nt":  # if running on windows, do not download obo file, but rather pass url directly to obonet
        obofile = url
    else:
        ontology_cache_dir = os.path.join(get_base_ontology_cache(), ontology_cache_dir)
        obofile = os.path.join(ontology_cache_dir, ontology_cache_fn)
        # Download if necessary:
        if not os.path.isfile(obofile):
            os.makedirs(name=ontology_cache_dir, exist_ok=True)

            def download_obo():
                print(f"Downloading: {ontology_cache_fn}")
                if not os.path.exists(ontology_cache_dir):
                    os.makedirs(ontology_cache_dir)
                r = requests.get(url, allow_redirects=True)
                open(obofile, 'wb').write(r.content)

            download_obo()
    return obofile


def cached_load_ebi(ontology_cache_dir, ontology_cache_fn) -> (networkx.MultiDiGraph, os.PathLike):
    """
    Load pickled graph object if available.

    :param ontology_cache_dir:
    :param ontology_cache_fn:
    :return:
    """
    ontology_cache_dir = os.path.join(get_base_ontology_cache(), ontology_cache_dir)
    picklefile = os.path.join(ontology_cache_dir, ontology_cache_fn)
    if os.path.isfile(picklefile):
        with open(picklefile, 'rb') as f:
            graph = pickle.load(f)
    else:
        os.makedirs(name=ontology_cache_dir, exist_ok=True)
        graph = None
    return graph, picklefile


class Ontology:
    leaves: List[str]

    @abc.abstractmethod
    def node_names(self):
        pass

    @abc.abstractmethod
    def map_node_suggestion(self, x: str, include_synonyms: bool = True, n_suggest: int = 10):
        """
        Map free text node name to ontology node names via fuzzy string matching.

        :param x: Free text node label which is to be matched to ontology nodes.
        :param include_synonyms: Whether to search for meaches in synonyms field of node instances, too.
        :return List of proposed matches in ontology.
        """
        pass

    def is_node(self, x: str):
        return x in self.node_names

    def validate_node(self, x: str):
        if not self.is_node(x=x):
            suggestions = self.map_node_suggestion(x=x, include_synonyms=False)
            raise ValueError(f"Node label {x} not found. Did you mean any of {suggestions}?")


class OntologyList(Ontology):
    """
    Basic unordered ontology container
    """
    nodes: list

    def __init__(
            self,
            terms: Union[List[Union[str, bool, int]]],
            **kwargs
    ):
        self.nodes = terms

    @property
    def node_names(self) -> List[str]:
        return self.nodes

    def map_node_suggestion(self, x: str, include_synonyms: bool = True, n_suggest: int = 10):
        """
        Map free text node name to ontology node names via fuzzy string matching.

        :param x: Free text node label which is to be matched to ontology nodes.
        :param include_synonyms: Whether to search for meaches in synonyms field of node instances, too.
        :param n_suggest: number of suggestions returned
        :return List of proposed matches in ontology.
        """
        from fuzzywuzzy import fuzz
        scores = np.array([
            np.max([
                fuzz.ratio(x.lower(), y.lower())
            ])
            for y in self.node_names
        ])
        # Suggest top n_suggest hits by string match:
        return [self.node_names[i] for i in np.argsort(scores)[-n_suggest:]][::-1]

    def synonym_node_properties(self) -> List[str]:
        return []

    def is_a(self, query: str, reference: str) -> bool:
        """
        Checks if query node is reference node.

        Note that there is no notion of ancestors for list ontologies.

        :param query: Query node name. Node ID or name.
        :param reference: Reference node name. Node ID or name.
        :return: If query node is reference node or an ancestor thereof.
        """
        return query == reference


class OntologyHierarchical(Ontology, abc.ABC):
    """
    Basic ordered ontology container
    """
    graph: networkx.MultiDiGraph

    def _check_graph(self):
        if not networkx.is_directed_acyclic_graph(self.graph):
            print(f"Ontology {type(self)} is not a DAG, treat child-parent reasoning with care.")

    def __validate_node_ids(self, x: Union[str, List[str]]):
        if isinstance(x, str):
            x = [x]
        node_ids = self.node_ids
        for y in x:
            if y not in node_ids:
                raise ValueError(f"queried node id {y} is not in graph")

    def __validate_node_names(self, x: Union[str, List[str]]):
        if isinstance(x, str):
            x = [x]
        node_names = self.node_names
        for y in x:
            if y not in node_names:
                raise ValueError(f"queried node name {y} is not in graph")

    @property
    def nodes(self) -> List[Tuple[str, dict]]:
        return list(self.graph.nodes.items())

    @property
    def nodes_dict(self) -> dict:
        return dict(list(self.graph.nodes.items()))

    @property
    def node_names(self) -> List[str]:
        return [x["name"] for x in self.graph.nodes.values()]

    @property
    def node_ids(self) -> List[str]:
        return list(self.graph.nodes())

    def is_a_node_id(self, x: str) -> bool:
        return x in self.node_ids

    def is_a_node_name(self, x: str) -> bool:
        return x in self.node_names

    def convert_to_name(self, x: Union[str, List[str]]) -> Union[str, List[str]]:
        was_str = isinstance(x, str)
        if was_str:
            x = [x]
        if self.is_a_node_id(x[0]):
            self.__validate_node_ids(x=x)
            x = [
                [v["name"] for k, v in self.graph.nodes.items() if k == z][0]
                for z in x
            ]
        elif self.is_a_node_name(x[0]):
            self.__validate_node_names(x=x)
        else:
            raise ValueError(f"node {x[0]} not recognized")
        self.__validate_node_names(x=x)
        if was_str:
            return x[0]
        else:
            return x

    def convert_to_id(self, x: Union[str, List[str]]) -> Union[str, List[str]]:
        was_str = isinstance(x, str)
        if was_str:
            x = [x]
        if self.is_a_node_id(x[0]):
            self.__validate_node_ids(x=x)
        elif self.is_a_node_name(x[0]):
            self.__validate_node_names(x=x)
            x = [
                [k for k, v in self.graph.nodes.items() if v["name"] == z][0]
                for z in x
            ]
        else:
            raise ValueError(f"node {x[0]} not recognized")
        self.__validate_node_ids(x=x)
        if was_str:
            return x[0]
        else:
            return x

    @property
    def leaves(self) -> List[str]:
        return [x for x in self.graph.nodes() if self.graph.in_degree(x) == 0]

    @leaves.setter
    def leaves(self, x: List[str]):
        """
        Sets new leaf-space for graph.

        This clips nodes that are not upstream of defined leaves.
        :param x: New set of leaves nodes, identified as IDs.
        """
        x = self.convert_to_id(x=x)
        nodes_to_remove = []
        for y in self.graph.nodes():
            if not np.any([self.is_a(query=z, reference=y) for z in x]):
                nodes_to_remove.append(y)
        self.graph.remove_nodes_from(nodes_to_remove)

    @property
    def n_leaves(self) -> int:
        return len(self.leaves)

    def get_effective_leaves(self, x: List[str]) -> List[str]:
        """
        Get effective leaves in ontology given set of observed nodes.

        The effective leaves are the minimal set of nodes such that all nodes in x are ancestors of this set, ie the
        observed nodes which represent leaves of a sub-DAG of the ontology DAG, which captures all observed nodes.

        :param x: Observed node IDs.
        :return: Effective leaves.
        """
        if isinstance(x, str):
            x = [x]
        if isinstance(x, np.ndarray):
            x = x.tolist()
        assert isinstance(x, list), "supply either list or str to get_effective_leaves"
        if len(x) == 0:
            raise ValueError("x was empty list, get_effective_leaves cannot be called on empty list")
        x = np.unique(x).tolist()
        x = self.convert_to_id(x=x)
        leaves = []
        for y in x:
            if not np.any([self.is_a(query=z, reference=y) for z in list(set(x) - {y})]):
                leaves.append(y)
        return leaves

    def get_ancestors(self, node: str) -> List[str]:
        node = self.convert_to_id(node)
        return list(networkx.ancestors(self.graph, node))

    def get_descendants(self, node: str) -> List[str]:
        node = self.convert_to_id(node)
        return list(networkx.descendants(self.graph, node))

    def is_a(self, query: str, reference: str) -> bool:
        """
        Checks if query node is reference node or an ancestor thereof.

        :param query: Query node name. Node ID or name.
        :param reference: Reference node name. Node ID or name.
        :return: If query node is reference node or an ancestor thereof.
        """
        query = self.convert_to_id(query)
        reference = self.convert_to_id(reference)
        return query in self.get_ancestors(node=reference) or query == reference

    def map_to_leaves(
            self,
            node: str,
            return_type: str = "ids",
            include_self: bool = True
    ) -> Union[List[str], np.ndarray]:
        """
        Map a given node to leave nodes.

        :param node:
        :param return_type:

            "ids": IDs of mapped leave nodes
            "idx": indicies in leave note list of mapped leave nodes
        :param include_self: whether to include node itself
        :return:
        """
        node = self.convert_to_id(node)
        ancestors = self.get_ancestors(node)
        if include_self:
            ancestors = ancestors + [node]
        if len(ancestors) > 0:
            ancestors = self.convert_to_id(ancestors)
        leaves = self.convert_to_id(self.leaves)
        if return_type == "ids":
            return [x for x in leaves if x in ancestors]
        elif return_type == "idx":
            return np.sort([i for i, x in enumerate(leaves) if x in ancestors])
        else:
            raise ValueError(f"return_type {return_type} not recognized")

    def prepare_maps_to_leaves(
            self,
            include_self: bool = True
    ) -> Dict[str, np.ndarray]:
        """
        Precomputes all maps of nodes to their leave nodes.

        :param include_self: whether to include node itself
        :return: Dictionary of index vectors of leave node matches for each node (key).
        """
        nodes = self.node_ids
        maps = {}
        import time
        t0 = time.time()
        for x in nodes:
            maps[x] = self.map_to_leaves(node=x, return_type="idx", include_self=include_self)
        print(f"time for precomputing ancestors: {time.time()-t0}")
        return maps

    @abc.abstractmethod
    def synonym_node_properties(self) -> List[str]:
        pass


class OntologyEbi(OntologyHierarchical):
    """
    Recursively assembles ontology by querying EBI web interface.

    Not recommended for large ontologies because of the iterative query of the web API.
    """

    def __init__(
            self,
            ontology: str,
            root_term: str,
            additional_terms: dict,
            additional_edges: List[Tuple[str, str]],
            ontology_cache_fn: str,
            **kwargs
    ):
        def get_url_self(iri):
            return f"https://www.ebi.ac.uk/ols/api/ontologies/{ontology}/terms/" \
                   f"http%253A%252F%252Fwww.ebi.ac.uk%252F{ontology}%252F{iri}"

        def get_url_children(iri):
            return f"https://www.ebi.ac.uk/ols/api/ontologies/{ontology}/terms/" \
                   f"http%253A%252F%252Fwww.ebi.ac.uk%252F{ontology}%252F{iri}/children"

        def get_iri_from_node(x):
            return x["iri"].split("/")[-1]

        def get_id_from_iri(x):
            x = ":".join(x.split("_"))
            return x

        def get_id_from_node(x):
            x = get_iri_from_node(x)
            x = get_id_from_iri(x)
            return x

        def recursive_search(iri):
            """
            This function queries all nodes that are children of a given node at one time. This is faster than querying
            the characteristics of each node separately but leads to slightly awkward code, the root node has to be
            queried separately for example below.

            :param iri: Root node IRI.
            :return: Tuple of

                - nodes (dictionaries of node ID and node values) and
                - edges (node ID of parent and child).
            """
            terms_children = requests.get(get_url_children(iri=iri)).json()["_embedded"]["terms"]
            nodes_new = {}
            edges_new = []
            direct_children = []
            k_self = get_id_from_iri(iri)
            # Define root node if this is the first iteration, this node is otherwise not defined through values.
            if k_self == "EFO:0010183":
                terms_self = requests.get(get_url_self(iri=iri)).json()
                nodes_new[k_self] = {
                    "name": terms_self["label"],
                    "description": terms_self["description"],
                    "synonyms": terms_self["synonyms"],
                    "has_children": terms_self["has_children"],
                }
            for c in terms_children:
                k_c = get_id_from_node(c)
                nodes_new[k_c] = {
                    "name": c["label"],
                    "description": c["description"],
                    "synonyms": c["synonyms"],
                    "has_children": c["has_children"],
                }
                direct_children.append(k_c)
                if c["has_children"]:
                    nodes_x, edges_x = recursive_search(iri=get_iri_from_node(c))
                    nodes_new.update(nodes_x)
                    # Update nested edges of between children:
                    edges_new.extend(edges_x)
            # Update edges to children:
            edges_new.extend([(k_self, k_c) for k_c in direct_children])
            return nodes_new, edges_new

        graph, picklefile = cached_load_ebi(ontology_cache_dir=ontology, ontology_cache_fn=ontology_cache_fn)
        if graph is None:
            self.graph = networkx.MultiDiGraph()
            nodes, edges = recursive_search(iri=root_term)
            nodes.update(additional_terms)
            edges.extend(additional_edges)
            for k, v in nodes.items():
                self.graph.add_node(node_for_adding=k, **v)
            for x in edges:
                parent, child = x
                self.graph.add_edge(child, parent)
            with open(picklefile, 'wb') as f:
                pickle.dump(obj=self.graph, file=f)
        else:
            self.graph = graph

    def map_node_suggestion(self, x: str, include_synonyms: bool = True, n_suggest: int = 10):
        """
        Map free text node name to ontology node names via fuzzy string matching.

        :param x: Free text node label which is to be matched to ontology nodes.
        :param include_synonyms: Whether to search for meaches in synonyms field of node instances, too.
        :return List of proposed matches in ontology.
        """
        from fuzzywuzzy import fuzz
        scores = np.array([
            np.max(
                [
                    fuzz.partial_ratio(x.lower(), v["name"].lower())
                ] + [
                    fuzz.partial_ratio(x.lower(), yyy.lower())
                    for yy in self.synonym_node_properties if yy in v.keys() for yyy in v[yy]
                ]
            ) if include_synonyms else
            np.max([
                fuzz.partial_ratio(x.lower(), v["name"].lower())
            ])
            for k, v in self.graph.nodes.items()
        ])
        # Suggest top n_suggest hits by string match:
        return [self.node_names[i] for i in np.argsort(scores)[-n_suggest:]][::-1]

    @property
    def synonym_node_properties(self) -> List[str]:
        return ["synonyms"]


# class OntologyOwl(OntologyHierarchical):
#
#    onto: owlready2.Ontology
#
#    def __init__(
#            self,
#            owl: str,
#            **kwargs
#    ):
#        self.onto = owlready2.get_ontology(owl)
#        self.onto.load()
#        # ToDo build support here
#
#    @property
#    def node_names(self):
#        pass


class OntologyObo(OntologyHierarchical, abc.ABC):

    def __init__(
            self,
            obo: str,
            **kwargs
    ):
        self.graph = obonet.read_obo(obo)

    def map_node_suggestion(self, x: str, include_synonyms: bool = True, n_suggest: int = 10):
        """
        Map free text node name to ontology node names via fuzzy string matching.

        :param x: Free text node label which is to be matched to ontology nodes.
        :param include_synonyms: Whether to search for meaches in synonyms field of node instances, too.
        :return List of proposed matches in ontology.
        """
        from fuzzywuzzy import fuzz
        scores = np.array([
            np.max(
                [
                    fuzz.ratio(x.lower().strip("'").strip("\""), y[1]["name"].lower())
                ] + [
                    fuzz.ratio(x.lower().strip("'").strip("\"").strip("]").strip("["), yyy.lower())
                    for yy in self.synonym_node_properties if yy in y[1].keys() for yyy in y[1][yy]
                ]
            ) if "synonym" in y[1].keys() and include_synonyms else
            np.max([
                fuzz.ratio(x.lower().strip("'").strip("\""), y[1]["name"].lower())
            ])
            for y in self.nodes
        ])
        # Suggest top n_suggest hits by string match:
        return [self.nodes[i][1]["name"] for i in np.argsort(scores)[-n_suggest:]][::-1]


class OntologyExtendedObo(OntologyObo):
    """
    Basic .obo ontology extended by additional nodes and edges without breaking DAG.
    """

    def __init__(self, obo, **kwargs):
        super().__init__(obo=obo, **kwargs)

    def add_extension(self, dict_ontology: Dict[str, List[Dict[str, dict]]]):
        """
        Extend ontology by additional edges and nodes defined in a dictionary.

        Checks that DAG is not broken after graph assembly.

        :param dict_ontology: Dictionary of nodes and edges to add to ontology. Parsing:

            - keys: parent nodes (which must be in ontology)
            - values: children nodes (which can be in ontology), must be given as a dictionary in which keys are
                ontology IDs and values are node values..
                If these are in the ontology, an edge is added, otherwise, an edge and the node are added.
        :return:
        """
        for k, v in dict_ontology.items():
            assert isinstance(v, dict), "dictionary values should be dictionaries"
            # Check that parent node is present:
            if k not in self.node_ids:
                raise ValueError(f"key {k} was not in reference ontology")
            # Check if edge is added only, or edge and node.
            for child_node_k, child_node_v in v.items():
                if child_node_k not in self.node_ids:  # Add node
                    self.graph.add_node(node_for_adding=child_node_k, **child_node_v)
                # Add edge.
                self.graph.add_edge(k, child_node_k)
        # Check that DAG was not broken:
        self._check_graph()

    @property
    def synonym_node_properties(self) -> List[str]:
        return ["synonym"]


class OntologyUberon(OntologyExtendedObo):

    def __init__(
            self,
            **kwargs
    ):
        obofile = cached_load_obo(
            url="http://purl.obolibrary.org/obo/uberon.obo",
            ontology_cache_dir="uberon",
            ontology_cache_fn="uberon.obo",
        )
        super().__init__(obo=obofile)

        # Clean up nodes:
        nodes_to_delete = []
        for k, v in self.graph.nodes.items():
            # Only retain nodes which are  "anatomical collection" 'UBERON:0034925':
            # ToDo this seems to narrow, need to check if we need to constrain the nodes we use.
            if "name" not in v.keys():
                nodes_to_delete.append(k)
        for k in nodes_to_delete:
            self.graph.remove_node(k)

        # Clean up edges:
        # The graph object can hold different types of edges,
        # and multiple types are loaded from the obo, not all of which are relevant for us:
        # All edge types (based on previous download, assert below that this is not extended):
        edge_types = [
            'aboral_to',
            'adjacent_to',
            'anastomoses_with',
            'anterior_to',
            'anteriorly_connected_to',
            'attaches_to',
            'attaches_to_part_of',
            'bounding_layer_of',
            'branching_part_of',
            'channel_for',
            'channels_from',
            'channels_into',
            'composed_primarily_of',
            'conduit_for',
            'connected_to',
            'connects',
            'contains',
            'continuous_with',
            'contributes_to_morphology_of',
            'deep_to',
            'developmentally_induced_by',
            'developmentally_replaces',
            'develops_from',  # developmental DAG -> include because it reflects the developmental hierarchy
            'develops_from_part_of',  # developmental DAG -> include because it reflects the developmental hierarchy
            'develops_in',
            'directly_develops_from',  # developmental DAG -> include because it reflects the developmental hierarchy
            'distal_to',
            'distally_connected_to',
            'distalmost_part_of',
            'dorsal_to',
            'drains',
            'ends',
            'ends_with',
            'existence_ends_during',
            'existence_ends_during_or_before',
            'existence_ends_with',
            'existence_starts_and_ends_during',
            'existence_starts_during',
            'existence_starts_during_or_after',
            'existence_starts_with',
            'extends_fibers_into',
            'filtered_through',
            'has_boundary',
            'has_component',
            'has_developmental_contribution_from',
            'has_fused_element',
            'has_member',
            'has_muscle_antagonist',
            'has_muscle_insertion',
            'has_muscle_origin',
            'has_part',
            'has_potential_to_develop_into',
            'has_potential_to_developmentally_contribute_to',
            'has_skeleton',
            'immediate_transformation_of',
            'immediately_anterior_to',
            'immediately_deep_to',
            'immediately_posterior_to',
            'immediately_preceded_by',
            'immediately_superficial_to',
            'in_anterior_side_of',
            'in_central_side_of',
            'in_deep_part_of',
            'in_distal_side_of',
            'in_dorsal_side_of',
            'in_innermost_side_of',
            'in_lateral_side_of',
            'in_left_side_of',
            'in_outermost_side_of',
            'in_posterior_side_of',
            'in_proximal_side_of',
            'in_right_side_of',
            'in_superficial_part_of',
            'in_ventral_side_of',
            'indirectly_supplies',
            'innervated_by',
            'innervates',
            'intersects_midsagittal_plane_of',
            'is_a',  # term DAG -> include because it connect conceptual tissue groups
            'layer_part_of',
            'located_in',  # anatomic DAG -> include because it reflects the anatomic coarseness / hierarchy
            'location_of',
            'lumen_of',
            'luminal_space_of',
            'overlaps',
            'part_of',  # anatomic DAG -> include because it reflects the anatomic coarseness / hierarchy
            'postaxialmost_part_of',
            'posterior_to',
            'posteriorly_connected_to',
            'preaxialmost_part_of',
            'preceded_by',
            'precedes',
            'produced_by',
            'produces',
            'protects',
            'proximal_to',
            'proximally_connected_to',
            'proximalmost_part_of',
            'seeAlso',
            'serially_homologous_to',
            'sexually_homologous_to',
            'skeleton_of',
            'starts',
            'starts_with',
            'subdivision_of',
            'superficial_to',
            'supplies',
            'surrounded_by',
            'surrounds',
            'transformation_of',
            'tributary_of',
            'trunk_part_of',
            'ventral_to'
        ]
        edges_to_delete = []
        for i, x in enumerate(self.graph.edges):
            assert x[2] in edge_types, x
            if x[2] not in [
                "develops_from",
                'develops_from_part_of',
                'directly_develops_from',
                "is_a",
                "located_in",
                "part_of",
            ]:
                edges_to_delete.append((x[0], x[1]))
        for x in edges_to_delete:
            self.graph.remove_edge(u=x[0], v=x[1])
        self._check_graph()

    @property
    def synonym_node_properties(self) -> List[str]:
        return ["synonym", "latin term", "has relational adjective"]


class OntologyCl(OntologyExtendedObo):

    def __init__(
            self,
            branch: str,
            use_developmental_relationships: bool = False,
            **kwargs
    ):
        """

        Developmental edges are not desired in all interactions with this ontology, double-negative thymocytes are for
        example not an intuitive parent node for a fine grained T cell label in a non-thymic tissue.
        :param branch:
        :param use_developmental_relationships: Whether to keep developmental relationships.
        :param kwargs:
        """
        obofile = cached_load_obo(
            url=f"https://raw.github.com/obophenotype/cell-ontology/{branch}/cl.obo",
            ontology_cache_dir="cl",
            ontology_cache_fn=f"{branch}_cl.obo",
        )
        super().__init__(obo=obofile)

        # Clean up nodes:
        nodes_to_delete = []
        for k, v in self.graph.nodes.items():
            # Some terms are not associated with the namespace cell but are cell types,
            # we identify these based on their ID nomenclature here.
            if ("namespace" in v.keys() and v["namespace"] not in ["cell", "cl"]) or \
                    ("namespace" not in v.keys() and str(k)[:2] != "CL"):
                nodes_to_delete.append(k)
            elif "name" not in v.keys():
                nodes_to_delete.append(k)
        for k in nodes_to_delete:
            self.graph.remove_node(k)

        # Clean up edges:
        # The graph object can hold different types of edges,
        # and multiple types are loaded from the obo, not all of which are relevant for us:
        # All edge types (based on previous download, assert below that this is not extended):
        edge_types = [
            'is_a',  # nomenclature DAG -> include because of annotation coarseness differences
            'derives_from',
            'develops_from',  # developmental DAG -> include because of developmental differences
            'has_part',  # ?
            'develops_into',  # inverse developmental DAG -> do not include
            'part_of',
            'RO:0002120',  # ?
            'RO:0002103',  # ?
            'lacks_plasma_membrane_part',  # ?
        ]
        edges_to_delete = []
        if use_developmental_relationships:
            edges_allowed = ["is_a", "develops_from"]
        else:
            edges_allowed = ["is_a"]
        for i, x in enumerate(self.graph.edges):
            assert x[2] in edge_types, x
            if x[2] not in edges_allowed:
                edges_to_delete.append((x[0], x[1]))
        for x in edges_to_delete:
            self.graph.remove_edge(u=x[0], v=x[1])
        self._check_graph()

    @property
    def synonym_node_properties(self) -> List[str]:
        return ["synonym"]


class OntologyOboCustom(OntologyExtendedObo):

    def __init__(
            self,
            obo: str,
            **kwargs
    ):
        super().__init__(obo=obo, **kwargs)


# use OWL for OntologyHancestro


class OntologyHsapdv(OntologyExtendedObo):

    def __init__(
            self,
            **kwargs
    ):
        obofile = cached_load_obo(
            url="http://purl.obolibrary.org/obo/hsapdv.obo",
            ontology_cache_dir="hsapdv",
            ontology_cache_fn="hsapdv.obo",
        )
        super().__init__(obo=obofile)

        # Clean up nodes:
        nodes_to_delete = []
        for k, v in self.graph.nodes.items():
            if "name" not in v.keys():
                nodes_to_delete.append(k)
        for k in nodes_to_delete:
            self.graph.remove_node(k)

    @property
    def synonym_node_properties(self) -> List[str]:
        return ["synonym"]


class OntologyMmusdv(OntologyExtendedObo):

    def __init__(
            self,
            **kwargs
    ):
        obofile = cached_load_obo(
            url="http://purl.obolibrary.org/obo/mmusdv.obo",
            ontology_cache_dir="mmusdv",
            ontology_cache_fn="mmusdv.obo",
        )
        super().__init__(obo=obofile)

        # Clean up nodes:
        nodes_to_delete = []
        for k, v in self.graph.nodes.items():
            if "name" not in v.keys():
                nodes_to_delete.append(k)
        for k in nodes_to_delete:
            self.graph.remove_node(k)

    @property
    def synonym_node_properties(self) -> List[str]:
        return ["synonym"]


class OntologyMondo(OntologyExtendedObo):

    def __init__(
            self,
            **kwargs
    ):
        obofile = cached_load_obo(
            url="http://purl.obolibrary.org/obo/mondo.obo",
            ontology_cache_dir="mondo",
            ontology_cache_fn="mondo.obo",
        )
        super().__init__(obo=obofile)

        # Clean up nodes:
        nodes_to_delete = []
        for k, v in self.graph.nodes.items():
            if "name" not in v.keys():
                nodes_to_delete.append(k)
        for k in nodes_to_delete:
            self.graph.remove_node(k)

        # add healthy property
        # Add node "healthy" under root node "MONDO:0000001": "quality".
        # We use a PATO node for this label: PATO:0000461.
        self.add_extension(dict_ontology={
            "MONDO:0000001": {
                "PATO:0000461": {"name": "healthy"}
            },
        })

    @property
    def synonym_node_properties(self) -> List[str]:
        return ["synonym"]


class OntologyCellosaurus(OntologyExtendedObo):

    def __init__(
            self,
            **kwargs
    ):
        obofile = cached_load_obo(
            url="https://ftp.expasy.org/databases/cellosaurus/cellosaurus.obo",
            ontology_cache_dir="cellosaurus",
            ontology_cache_fn="cellosaurus.obo",
        )
        super().__init__(obo=obofile)

        # Clean up nodes:
        # edge_types = ["derived_from", "originate_from_same_individual_as"]
        nodes_to_delete = []
        for k, v in self.graph.nodes.items():
            if "name" not in v.keys():
                nodes_to_delete.append(k)
        for k in nodes_to_delete:
            self.graph.remove_node(k)

    @property
    def synonym_node_properties(self) -> List[str]:
        return ["synonym"]


class OntologySinglecellLibraryConstruction(OntologyEbi):

    def __init__(self):
        super().__init__(
            ontology="efo",
            root_term="EFO_0010183",
            additional_terms={
                "sci-plex": {"name": "sci-plex"},
                "sci-RNA-seq": {"name": "sci-RNA-seq"},
            },
            additional_edges=[
                ("EFO:0010183", "sci-plex"),
                ("EFO:0010183", "sci-RNA-seq"),
            ],
            ontology_cache_fn="efo.pickle"
        )