# Notes pour le backend <!-- omit in toc -->

## Table des matières <!-- omit in toc -->

- [Installation des dépendances via conda](#installation-des-dépendances-via-conda)
- [Architecture du code](#architecture-du-code)

## Installation des dépendances via conda

Pour installer toutes les dépendances en créant un **nouvel env conda**, il suffit simplement d'entrer dans le terminal à la racine du dossier :
`conda env create -f environment.yml`. Cette commande va automatiquement créer le nouvel env conda avec le nom renseigné dans le fichier `environment.yml` (i.e. _DartsifyBackend_) en installant les versions spécifiques de chaque librairie. Pour spécifier manuellement un autre nom de fichier, il faut ajouter `-n mon-env-fastapi` à la fin de la commande (avec le bon nom désiré).

Pour mettre à jour les librairies d'un **env conda déjà existant**, il suffit d'entrer dans le terminal, après avoir activé l'env désiré : `conda env update --file environment.yml --prune`. Ceci va mettre à jour un env **déjà créé**.

## Architecture du code

**Faisons gaffe à la lisibilité du code pour pouvoir débug facilement**
Donc pour ça, il faut vraiment séparer le code en plusieurs fichiers, tout garder dans un seul ça va vite devenir illisible. J'ai trouvé cette **documentation officielle** ([lien vers la doc](https://fastapi.tiangolo.com/tutorial/bigger-applications/#an-example-file-structure)). Je vois comme configuration :

- La config de l'_API_ (donc écrite une seule fois, comme la déclaration de la session etc), e.g. :

  ```python
  # Creat an engine(what holds the connection with db) -> one single engine object for the entire app
  sqlite_file_name = "database.db"
  sqlite_url = f"sqlite:///{sqlite_file_name}"

  connect_args = {"check_same_thread": False} # allows FastAPI to use the same SQLite database in diff threads (necessary)
  engine = create_engine(sqlite_url, connect_args=connect_args)

  # Create the tables
  def create_db_and_tables():
      SQLModel.metadata.create_all(engine) # create the tables for all the table models

  # Create Session dependency -> session is what stores the objects in memory and keeps track of any changes (then uses the engine to communicate with the database and save the changes)
  def get_session():
      with Session(engine) as session:
          yield session # new session for each request (single session per request)


  SessionDep = Annotated[Session, Depends(get_session)] # we will use this Annotated Dependency to simplify the rest of the code (that will use this dep.)

  # Create database tables on startup (when the app starts)
  app = FastAPI()

  @app.on_event("startup")
  def on_startup():
      create_db_and_tables()
  ```

  On peut mettre ceci dans un fichier `main.py`

- La déclaration des différentes classes, e.g. :

  ```python
  class Hero(SQLModel, table=True):
      id: int | None = Field(default=None, primary_key=True)
      name: str = Field(index=True)
      age: int | None = Field(default=None, index=True)
      secret_name: str
  ```

  On peut stocker ces classes dans un fichier `models.py` ou plutôt partir sur un dossier `models` et y placer plusieurs fichiers afin de séparer les différentes partie (e.g. `models/users.py`, `models/parties.py`). À **Adrien** de voir comment séparer tout ça.

- La déclaration des requêtes, e.g. :

  ```python
  router = APIRouter(prefix="/heroes", tags=["heroes"])
  # tags sert à organiser la documentation automatique Swagger UI ( /docs ) et ReDoc ( /redoc ) ;
  # router permet de préfixer toutes les requêtes ici par /heroes (nous n'avons ici que les requêtes sur les heroes)

  @router.delete("/{hero_id}")
  def delete_hero(hero_id: int, session: SessionDep):
      hero = session.get(Hero, hero_id)
      if not hero:
          raise HTTPException(status_code=404, detail="Hero not found")
      session.delete(hero)
      session.commit()
      return {"ok": True}
  ```

  On peut stocker ces requêtes dans un dossier `routers` et séparer les fichiers selon les types de données (e.g. `routers/heroes.py`).
