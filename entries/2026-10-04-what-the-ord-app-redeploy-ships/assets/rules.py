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

"""Validate one reaction under targeted mutations; print errors per mutation as JSON."""

import json

from ord_schema.proto import reaction_pb2
from ord_schema.validations import ValidationOptions, validate_message


def base():
    reaction = reaction_pb2.Reaction()
    component = reaction.inputs["a"].components.add()
    component.identifiers.add(type="SMILES", value="CCO")
    component.amount.mass.value = 1
    component.amount.mass.units = reaction_pb2.Mass.GRAM
    component.reaction_role = reaction_pb2.ReactionRole.REACTANT
    product = reaction.outcomes.add().products.add()
    product.identifiers.add(type="SMILES", value="CC=O")
    reaction.provenance.record_created.time.value = "2026-01-01"
    reaction.provenance.record_created.person.username = "someone"
    reaction.provenance.record_created.person.email = "someone@example.com"
    return reaction


def ph(r): r.conditions.ph = 15
def workup_ph(r): r.workups.add(type="CUSTOM", details="x", target_ph=-1)
def orcid(r): r.provenance.record_created.person.orcid = "0000-0002-1825-0098"
def orcid_unanchored(r): r.provenance.record_created.person.orcid = "x0000-0002-1825-0097x"
def cas(r): r.inputs["a"].components[0].identifiers.add(type="CAS_NUMBER", value="64175")
def inchikey(r): r.inputs["a"].components[0].identifiers.add(type="INCHI_KEY", value="notakey")
def pubchem(r): r.inputs["a"].components[0].identifiers.add(type="PUBCHEM_CID", value="abc")
def url(r): r.provenance.publication_url = "not a url"
def electro(r): r.conditions.electrochemistry.type = reaction_pb2.ElectrochemistryConditions.ElectrochemistryType.CONSTANT_CURRENT
def dark(r):
    r.conditions.illumination.type = reaction_pb2.IlluminationConditions.IlluminationType.DARK
    r.conditions.illumination.peak_wavelength.value = 400
    r.conditions.illumination.peak_wavelength.units = reaction_pb2.Wavelength.NANOMETER
def mapped(r): r.identifiers.add(type="REACTION_CXSMILES", value="[CH3:1][OH:2]>>[CH3:1][OH:2]")
def stirring_workup(r): r.workups.add(type="STIRRING")
def mz(r):
    m = r.outcomes[0].products[0].measurements.add(type="IDENTITY", analysis_key="ms")
    m.mass_spec_details.type = reaction_pb2.ProductMeasurement.MassSpecMeasurementDetails.MassSpecMeasurementType.TIC
    m.mass_spec_details.tic_minimum_mz = 500
    m.mass_spec_details.tic_maximum_mz = 100
    r.outcomes[0].analyses["ms"].type = reaction_pb2.Analysis.AnalysisType.MS


options = ValidationOptions(require_provenance=True)
out = {}
for name, mutate in [("base", None)] + [(f.__name__, f) for f in (ph, workup_ph, orcid, orcid_unanchored, cas, inchikey, pubchem, url, electro, dark, mapped, stirring_workup, mz)]:
    reaction = base()
    if mutate:
        mutate(reaction)
    result = validate_message(reaction, raise_on_error=False, options=options)
    out[name] = {"errors": result.errors, "warnings": result.warnings}
print(json.dumps(out))
