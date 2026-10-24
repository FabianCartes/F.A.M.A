"""Effective recording groups from canonical, human-reviewed source references.

The reference establishes catalog lineage, not acoustic proof of common origin.
Unknown human feedback stays together; ordinary recordist groups never split.
"""


def recording_groups(frame, dataset_name):
    rows = frame.to_dict("records")
    originals = {}
    if dataset_name == "AvesChilenas":
        for row in rows:
            identity = row.get("xc_id")
            if identity in originals:
                raise ValueError("Duplicate recording identity in curation source catalog")
            originals[identity] = row
    groups = {}
    for row in rows:
        group = row["recordist"]
        source_id = row.get("curation_source_id", "")
        if source_id:
            source = originals.get(source_id)
            if (dataset_name != "AvesChilenas" or group != "human_feedback" or source is None
                    or source["recordist"] == "human_feedback"
                    or source.get("curation_source_id", "")):
                raise ValueError("Invalid curation source: require an original canonical bird recording")
            group = source["recordist"]
        groups[(row["file_stage"], row["file_path"])] = group
    return groups
