# Copyright 2026 Open Reaction Database Project Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""What is lost if compound identifiers collapse to a single SMILES?"""
import collections, glob, json
from ord_schema import parquet
from ord_schema.proto import reaction_pb2

CID = reaction_pb2.CompoundIdentifier
STRUCTURAL = {CID.SMILES, CID.CXSMILES, CID.INCHI, CID.MOLBLOCK}
name_of = CID.CompoundIdentifierType.Name

total = 0
have_structural = 0
name_only = 0
no_identifiers = 0
types = collections.Counter()
nonstructural_present = collections.Counter()

for path in sorted(glob.glob("/Users/skearnes/ord/ord-data/data/*/*.parquet")):
    for item in parquet.iter_reactions(path):
        reaction = item[1] if isinstance(item, tuple) else item
        compounds = []
        for reaction_input in reaction.inputs.values():
            compounds.extend(reaction_input.components)
        for outcome in reaction.outcomes:
            compounds.extend(outcome.products)
        for compound in compounds:
            total += 1
            present = {i.type for i in compound.identifiers if i.value}
            for t in present:
                types[name_of(t)] += 1
            if not present:
                no_identifiers += 1
                continue
            if present & STRUCTURAL:
                have_structural += 1
                for t in present - STRUCTURAL:
                    nonstructural_present[name_of(t)] += 1
            elif present == {CID.NAME}:
                name_only += 1

print(json.dumps({
    "compounds": total,
    "with_structural_identifier": have_structural,
    "name_only": name_only,
    "no_identifiers": no_identifiers,
    "lost_if_collapsed_to_smiles": total - have_structural,
    "identifier_types": dict(types.most_common()),
    "non_structural_alongside_structural": dict(nonstructural_present.most_common(6)),
}, indent=2))
