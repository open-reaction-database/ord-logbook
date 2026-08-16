-- Copyright 2026 Open Reaction Database Project Authors
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.

-- Query pairs behind 2026-07-31-projection-search-index.
-- Substitute the projection glob for :projection and the fact table for :facts.

-- Finding 1: identical predicate, 27-200x apart. UNNEST materializes the exploded
-- intermediate; the lambda form scans list child arrays in place.
-- Slow: did not finish in four minutes over the full corpus.
SELECT count(DISTINCT reaction_id)
FROM :projection,
     UNNEST(map_values(inputs)) t(i),
     UNNEST(i.components) u(c),
     UNNEST(c.identifiers) v(x)
WHERE x.type = 'NAME' AND x.value = 'THF';

-- Fast: 0.90 s over the full corpus, same answer (145,285).
SELECT count(*)
FROM :projection
WHERE len(list_filter(
        flatten(list_transform(map_values(inputs), i -> i.components)),
        c -> len(list_filter(c.identifiers, x -> x.type = 'NAME' AND x.value = 'THF')) > 0)) > 0;

-- Finding 2: intra-component conjunction, native to the nested form (0.80 s, 91,683).
-- Both predicates must hold for the SAME component.
SELECT count(*)
FROM :projection
WHERE len(list_filter(
        flatten(list_transform(map_values(inputs), i -> i.components)),
        c -> len(list_filter(c.identifiers, x -> x.type = 'NAME' AND x.value = 'THF')) > 0
             AND c.amount.volume_liters > 0.005)) > 0;

-- Finding 2: role division. Outputs live under outcomes[*].products.
SELECT count(*)
FROM :projection
WHERE len(list_filter(
        flatten(list_transform(outcomes, o -> o.products)), p -> p.smiles = 'C1CCOC1')) > 0;

-- Finding 3: the same selections against the fact table, 13x faster.
SELECT count(DISTINCT reaction_id) FROM :facts
WHERE role = 'INPUT' AND identifier_type = 'NAME' AND identifier_value = 'THF';   -- 0.068 s

SELECT count(DISTINCT reaction_id) FROM :facts
WHERE role = 'INPUT' AND smiles = 'C1CCOC1';                                      -- 0.052 s

-- Finding 3: co-membership reconstructed via the entity key (0.070 s). Dropping
-- component_index from the join silently answers a different question -- "a reaction
-- containing an X and a Y" rather than "one component that is both".
SELECT count(DISTINCT a.reaction_id)
FROM :facts a
JOIN :facts b
  ON a.reaction_id = b.reaction_id
 AND a.role = b.role
 AND a.component_index = b.component_index
WHERE a.identifier_type = 'NAME' AND a.identifier_value = 'THF'
  AND b.identifier_type = 'CAS_NUMBER';
