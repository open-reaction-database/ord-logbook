# Auth0 ORCID custom-connection `fetchUserProfile` script (recovered)

- **Date:** 2026-07-15
- **Author:** Claude Code (Fable 5), for Steven Kearnes
- **Status:** archived reference
- **Tags:** ord-app, auth0, orcid, authentication, configuration
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Context

ord-app's ORCID login runs through an Auth0 **custom social connection**, and
the `fetchUserProfile` script that maps an ORCID access token to an Auth0 user
profile lives only in the Auth0 dashboard — it is not tracked in any repo. A
copy turned up as `test.js` in a git stash in a local ord-app checkout
(stashed 2026-05-30, on `main` at 39230a2); the rest of that stash was a stray
local PostgreSQL data directory and was not worth preserving. This entry
archives the script so the Auth0 configuration has a versioned reference.

## What the script does

Given the OAuth access token and the connection context, it:

1. Fetches the user's public profile from the ORCID Public API
   (`https://pub.orcid.org/v3.0/<orcid>`).
2. Extracts the primary email (empty string if none is public) and the
   given/family names.
3. Builds the Auth0 profile with `user_id` and `orcid` set to the ORCID iD,
   and `name` falling back from the context name to `given family` to the
   ORCID iD itself.

## The script

```js
/**
 * Copyright 2025 Open Reaction Database Project Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

function (accessToken, context, cb) {
    const request = require('request');
    // Request options to get ORCID user profile information via Public API
    const options = {
        url: `https://pub.orcid.org/v3.0/${context.orcid}`,
        headers: {
            'Authorization': `Bearer ${accessToken}`
        },
        json: true
    };
    const getPrimaryEmail = (orcidResponse) => {
        // Extract the email list from the ORCID response
        const emailList = orcidResponse.person?.emails?.email || [];
        // Iterate through the email list
        for (const email of emailList) {
            if (email.primary) {
                // Return primary email
                return email.email;
            }
        }
        // Return a fallback message if no email is found
        return '';
    };
    const getUserNameByType = (orcidResponse, type) => {
        // Extract the name object from the ORCID response
        const name = orcidResponse.person?.name || {};
        // Return ORCID given-names or family-name
        return name[type]?.value || '';
    };
    request.get(options, (err, response, body) => {
        if (err) {
            return cb(err);
        }
        if (response.statusCode !== 200) {
            return cb(new Error('Failed to fetch user profile: ' + JSON.stringify(body)));
        }
        const givenNames = getUserNameByType(body, "given-names");
        const familyName = getUserNameByType(body, "family-name");
        const profile = {
            user_id: context.orcid,
            name: context.name || `${givenNames} ${familyName}`.trim() || context.orcid,
            email: getPrimaryEmail(body),
            given_names: givenNames,
            family_name: familyName,
            orcid: context.orcid
        };
        cb(null, profile);
    });
}
```

## Notes / next steps

- If the script in the Auth0 dashboard drifts from this copy, the dashboard
  is authoritative — update this entry.
- Consider managing the Auth0 tenant as code (e.g. the Auth0 Deploy CLI or a
  Pulumi/Terraform provider) so scripts like this are versioned at the source.
