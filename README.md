# Letterboxd Spotlight

Every 14 days this takes the top trending lists on Letterboxd, copies their films into
5 MDBList lists, and makes a new cover for each one. Add the 5 lists to AIOMetadata once;
after that the rows and covers in Strand change on their own.

## One-time setup

### 1. Make 5 empty lists on MDBList
On mdblist.com, create 5 **static** lists (for example "Trending on Letterboxd 1" to "5").

### 2. Put these files in a new GitHub repo
Create a **public** repo (e.g. `letterboxd-spotlight`) and upload everything in this folder,
including the `.github` folder and `fonts` folder.

### 3. Add your keys
In the repo: **Settings > Secrets and variables > Actions**

**Secrets** tab, "New repository secret":
- `MDBLIST_API_KEY`: from MDBList > Preferences
- `TMDB_API_KEY`: your TMDB API key (the same one AIOMetadata uses works)

### 4. Allow it to save covers
**Settings > Actions > General > Workflow permissions** > choose **Read and write permissions** > Save.

### 5. Find your list ID numbers
**Actions** tab > "Rotate Letterboxd Spotlight" > **Run workflow** > pick `show-my-lists` > Run.
Open the finished run and click "Run spotlight" to see each list with its ID number.

Then back in **Settings > Secrets and variables > Actions**, **Variables** tab, add:
- `MDBLIST_LIST_IDS`: the 5 ID numbers in order, separated by commas (e.g. `12345,12346,12347,12348,12349`)

Optional variables:
- `ROTATE_EVERY_DAYS`: default 14
- `EXCLUDE_WORDS`: skip lists whose title contains these words, comma separated (e.g. `anime,horror`)

### 6. Do the first rotation
**Actions** > **Run workflow** > `force`. When it finishes (green check), the `covers` folder has
`trending-1.png` to `trending-5.png` and your MDBList lists are filled.

### 7. Hook it up to AIOMetadata / Strand
- Add each MDBList list in AIOMetadata (Quick Add, paste the list's MDBList link).
- Set each catalog's cache time to about 1 day.
- For each row's cover image, use:
  `https://raw.githubusercontent.com/YOUR-USERNAME/letterboxd-spotlight/main/covers/trending-1.png`
  (change the number for each slot).

## After that
It runs itself every Monday and rotates when 14 days have passed. `state.json` shows which
Letterboxd lists are in each slot right now. If Letterboxd ever blocks it, the run shows a red X,
GitHub emails you, and nothing changes until the next successful run.

Fonts: Bebas Neue and Montserrat, SIL Open Font License.
