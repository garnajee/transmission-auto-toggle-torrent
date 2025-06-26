# Étape 1: Utiliser une image Python légère comme base
FROM python:3.11-slim

# Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Copier le fichier des dépendances
COPY requirements.txt .

# Installer les dépendances en désactivant le cache pour réduire la taille de l'image
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste du code de l'application
COPY app.py .

EXPOSE 8080

# La commande par défaut qui sera exécutée au lancement du conteneur
#CMD ["python", "app.py"]
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "3", "app:app"]
