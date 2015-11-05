import os, re, requests, yaml
from itertools import combinations
from requests.models import RequestEncodingMixin

from config import API
from datausa import app
from datausa.visualize.models import Viz
from datausa.utils.data import attr_cache, col_map, datafold, default_params, fetch, stat
from datausa.utils.format import num_format


geo_labels = {
    "010": "nation",
    "040": "state",
    "050": "county",
    "310": "MSA",
    "160": "census designated place",
    "860": "zip code",
    "795": "PUMA",
    "140": "census tract"
}

geo_sumlevels = {
    "010": "us",
    "040": "state",
    "050": "county",
    "310": "msa",
    "160": "place",
    "860": "zip",
    "795": "puma",
    "140": "tract"
}

geo_children = {
    "010": "040",
    "040": "050",
    "050": "140"
}


class Section(object):
    """A section of a profile page that contains many horizontal text/viz topics.

    Attributes:
        attr (dict): Attribute of profile.
        description (str): Description of the Section, read from YAML configuration.
        profile (Profile): Profile the Section lives within.
        title (str): Title of the Section, read from YAML configuration.
        topics (List[dict]): List of the various topic dictionaries in the Section.

    """

    def __init__(self, f, profile):
        """Initializes a new Section class.

        Args:
            config (str): The YAML configuration file as one long string.
            profile (Profile): The Profile class instance this Section will be a part of.

        """


        profile_path = os.path.dirname(os.path.realpath(__file__))
        file_path = os.path.join(profile_path, profile.attr_type, "{}.yml".format(f))
        config = "".join(open(file_path).readlines())

        # Set the attr and profile attributes
        self.attr = profile.attr
        self.anchor = f
        self.profile = profile

        # regex to find all keys matching {{*}}
        keys = re.findall(r"\{\{([^\}]+)\}\}", config)

        # loop through each key
        for k in keys:
            # split the key at a blank space to find params
            val = re.findall(r"<<([^>]+)>>", k)[0]
            func, params = val.split(" ") if " " in val else (val, "")

            # if Section has a function with the same name as the key
            if hasattr(self, func):

                # convert params into a dict, splitting at pipes
                params = dict(item.split("=") for item in params.split("|")) if params else {}
                # run the Section function, passing the params as kwargs
                ret = getattr(self, func)(**params)

                if func in self.attr and self.attr[func] == ret:
                    # if the attr has this attribute and it's the same, remove it
                    ret = ""
                else:
                    # else, replace it with the returned value
                    ret = k.replace("<<{}>>".format(val), ret)

            # replace all instances of key with the returned value
            config = config.replace("{{{{{}}}}}".format(k), ret)


        # regex to find all keys matching <<*>>
        keys = re.findall(r"<<([^>]+)>>", config)

        # loop through each key
        for k in keys:
            # split the key at a blank space to find params
            func, params = k.split(" ") if " " in k else (k, "")

            # if Section has a function with the same name as the key
            if hasattr(self, func):
                # convert params into a dict, splitting at pipes
                params = dict(item.split("=") for item in params.split("|")) if params else {}
                # run the Section function, passing the params as kwargs
                val = getattr(self, func)(**params)

                # if it returned an object, convert it to string
                if isinstance(val, (int, long, float, complex)):
                    val = str(val)
                elif isinstance(val, dict):
                    col = params.get("col", "name")
                    if col == "id":
                        val = val["value"]
                    else:
                        val = "<span data-url='{}'>{}</span>".format(val["url"], val["value"])

                # replace all instances of key with the returned value
                config = config.replace("<<{}>>".format(k), val.encode("utf-8"))

        # load the config through the YAML interpreter and set title, description, and topics
        config = yaml.load(config)

        if "title" in config:
            self.title = config["title"]

        if "description" in config:
            self.description = config["description"]
            if not isinstance(self.description, list):
                self.description = [self.description]

        if "topics" in config:
            self.topics = config["topics"]

            self.topics = [t for t in self.topics if self.allowTopic(t)]

            # loop through the topics
            for topic in self.topics:

                if "description" in topic and not isinstance(topic["description"], list):
                    topic["description"] = [topic["description"]]

                # instantiate the "viz" config into an array of Viz classes
                if "viz" in topic:
                    if not isinstance(topic["viz"], list):
                        topic["viz"] = [topic["viz"]]
                    topic["viz"] = [Viz(viz, color=self.profile.color(), highlight=self.attr["id"]) for viz in topic["viz"]]

                if "miniviz" in topic:
                    topic["miniviz"] = Viz(topic["miniviz"], color=self.profile.color(), highlight=self.attr["id"])

                # fill selector if present
                if "select" in topic:
                    if isinstance(topic["select"]["data"], str):
                        topic["select"]["param"] = topic["select"]["data"]
                        topic["select"]["data"] = [v for k, v in attr_cache[topic["select"]["data"]].iteritems()]
                    elif isinstance(topic["select"]["data"], list):
                        topic["select"]["data"] = [fetch(v, False) for v in topic["select"]["data"]]

        if "sections" in config:
            self.sections = config["sections"]

        if "stats" in config:
            self.stats = config["stats"]

        if "facts" in config:
            self.facts = config["facts"]

    def allowTopic(self, topic):
        """bool: Returns whether or not a topic is allowed for a specific profile """
        if "sumlevel" in topic:
            levels = [t for t in topic["sumlevel"].split(",")]
            if self.profile.attr_type == "geo":
                level = geo_sumlevels[self.attr["id"][:3]]
            else:
                level = len(self.attr["id"])

            return level in levels

        return True

    def children(self, **kwargs):
        attr_id = kwargs.get("attr_id", self.id(**kwargs))
        prefix = attr_id[:3]
        if kwargs.get("dataset", False) == "chr" and prefix not in ["010", "040"]:
            attr_id = self.profile.parents()[1]["id"]
            prefix = "040"
        if kwargs.get("prefix", False) and prefix in geo_children:
            return attr_id.replace(prefix, geo_children[prefix])
        return ",".join([c["id"] for c in self.profile.children(attr_id=attr_id)])

    def id(self, **kwargs):
        """str: The id of attribute taking into account the dataset and grainularity of the Section """

        # if there is a specified dataset in kwargs
        if "dataset" in kwargs:
            dataset = kwargs["dataset"]
            # if the attribute is a CIP and the dataset is PUMS, return the parent CIP code
            if self.profile.attr_type == "cip" and dataset == "pums":
                return self.attr["id"][:2]
            elif self.profile.attr_type == "geo" and dataset == "chr":
                attr_id = self.attr["id"]
                prefix = attr_id[:3]
                if kwargs.get("parent", False) and prefix not in ["010", "040"]:
                    attr_id = self.profile.parents()[1]["id"]
                    prefix = "040"

                if prefix in ["010", "040", "050"]:
                    return attr_id
                else:
                    return self.profile.parents()[2]["id"]

        return self.attr["id"]

    def level(self, **kwargs):
        """str: A string representation of the depth type. """
        attr_type = kwargs.get("attr_type", self.profile.attr_type)
        attr_id = kwargs.get("attr_id", self.id(**kwargs))
        dataset = kwargs.get("dataset", False)

        if attr_type == "geo":
            prefix = attr_id[:3]
            if dataset == "chr" and prefix not in ["010", "040"]:
                prefix = "040"
            if kwargs.get("child", False) and prefix in geo_children:
                prefix = geo_children[prefix]
            name = geo_labels[prefix]
        else:
            name = attr_type

        if "plural" in kwargs:
            name = "{}ies".format(name[:-1]) if name[-1] == "y" else "{}s".format(name)

        if "uppercase" in kwargs:
            name = name.capitalize()

        return name

    def name(self, **kwargs):
        """str: The attribute name """

        if "id" in kwargs and "attr" in kwargs:
            return fetch(kwargs["id"], kwargs["attr"])["name"]
        elif "dataset" in kwargs:
            return fetch(self.id(**kwargs), self.profile.attr_type)["name"]

        return self.attr["name"]

    def parents(self, **kwargs):
        return ",".join([p["id"] for p in self.profile.parents()])

    def percent(self, **kwargs):
        """str: 2 columns divided by one another """

        # set default params
        params = {}
        attr_type = kwargs.get("attr_type", self.profile.attr_type)
        params[attr_type] = kwargs.get("attr_id", self.attr["id"])
        params["limit"] = 1
        params["show"] = params.get("show", attr_type)
        params = default_params(params)

        r = {"num": 1, "den": 1}
        for t in r.keys():
            key = kwargs.get(t)

            if "top:" in key:

                if "required" in params:
                    del params["required"]

                params["col"], params["force"] = key.split(":")[1].split(",")
                r[t] = self.top(**params)["data"][0]

            else:

                if "col" in params:
                    del params["col"]
                if "force" in params:
                    del params["force"]

                params["required"] = key

                # convert request arguments into a url query string
                query = RequestEncodingMixin._encode_params(params)
                url = "{}/api?{}".format(API, query)

                try:
                    r[t] = datafold(requests.get(url).json())[0][key]
                except ValueError:
                    app.logger.info("STAT ERROR: {}".format(url))
                    return "N/A"

        val = r["num"]/r["den"]
        if kwargs.get("invert", False):
            val = 1 - val
        return "{}%".format(num_format(val * 100))

    def sub(self, **kwargs):
        kwargs["data_only"] = True
        attr_type = kwargs.get("attr_type", self.profile.attr_type)
        subs = self.top(**kwargs)["subs"]
        if attr_type in subs and subs[attr_type] != self.attr["id"]:
            return "Based on data from {}".format(fetch(subs[attr_type], attr_type)["name"])
        else:
            return ""

    def sumlevel(self, **kwargs):
        """str: A string representation of the depth type. """
        attr_type = kwargs.get("attr_type", self.profile.attr_type)
        attr_id = kwargs.get("attr_id", self.id(**kwargs))

        if attr_type == "geo":
            prefix = attr_id[:3]
            if kwargs.get("child", False) and prefix in geo_children:
                if kwargs.get("dataset", False) == "chr" and prefix not in ["010", "040"]:
                    prefix = "040"
                prefix = geo_children[prefix]
            name = geo_sumlevels[prefix]
        else:
            name = attr_type

        if "plural" in kwargs:
            name = "{}ies".format(name[:-1]) if name[-1] == "y" else "{}s".format(name)

        return name

    def top(self, **kwargs):
        """str: A text representation of a top statistic or list of statistics """

        attr_type = kwargs.get("attr_type", self.profile.attr_type)
        dataset = kwargs.get("dataset", False)

        # create a params dict to use in the URL request
        params = {}

        # set the section's attribute ID in params
        attr_id = kwargs.get("attr_id", False)
        child = kwargs.get("child", False)
        if attr_id == False:
            if child:
                aid = self.id(**kwargs)
                prefix = aid[:3]
                if dataset == "chr" and prefix not in ["010", "040"]:
                    aid = self.profile.parents()[1]["id"]
                    prefix = "040"
                if prefix in geo_children:
                    params["where"] = "geo:^{}".format(aid.replace(prefix, geo_children[prefix]))
                    attr_id = ""
        if attr_id == False:
            attr_id = self.id(**kwargs)
        params[attr_type] = attr_id

        # get output key from either the value in kwargs (while removing it) or 'name'
        col = kwargs.pop("col", "name")
        data_only = kwargs.pop("data_only", False)
        if child:
            kwargs["sumlevel"] = self.sumlevel(**kwargs)

        if "child" in kwargs:
            del kwargs["child"]
        if "dataset" in kwargs:
            del kwargs["dataset"]

        # add the remaining kwargs into the params dict
        params = dict(params.items()+kwargs.items())

        # set default params
        params["limit"] = params.get("limit", 1)
        params["show"] = params.get("show", attr_type)
        params = default_params(params)

        col_maps = col_map.keys()
        col_maps += ["-".join(c) for c in list(combinations(col_maps, 2))]
        col_maps += ["id", "name", "ratio"]
        if col not in col_maps:
            params["required"] = col
        elif "required" not in params:
            params["required"] = params["order"]

        # make the API request using the params
        return stat(params, col=col, dataset=dataset, data_only=data_only)

    def var(self, **kwargs):
        namespace = kwargs["namespace"]
        key = kwargs["key"]

        var_map = self.profile.variables
        if var_map:
            if "row" in kwargs and namespace in var_map and var_map[namespace]:
                row = int(kwargs["row"])
                if row < len(var_map[namespace]):
                    return var_map[namespace][row][key]
            if namespace in var_map and key in var_map[namespace]:
                return var_map[namespace][key]
            return "N/A"
        else:
            raise Exception("vars.yaml file has no variables")

    def __repr__(self):
        return "Section: {}".format(self.title)
