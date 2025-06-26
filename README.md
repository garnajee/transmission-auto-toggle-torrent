# Transmission Auto Toggle Torrent

A lightweight, web-based utility to automatically manage specific trackers in a Transmission instance. This tool disables target trackers on incomplete torrents and re-enables them upon completion. Ideal for private trackers that have strict ratio rules or for managing public trackers you only want to seed from.

It features a simple web UI to dynamically configure settings without restarting the container.

## Features

-   **Automatic Tracker Toggling**: Disables specified trackers while a torrent is downloading and re-enables them once it's 100% complete.
-   **Lightweight Web Interface**: Manage the service from a simple, resource-friendly web UI.
-   **Dynamic Configuration**:
    -   Enable or disable the service on the fly.
    -   Add or remove target tracker URLs without restarting.
-   **Persistent State**: Configuration is saved and persists across container restarts.
-   **Dockerized**: Easy to deploy and manage using Docker and Docker Compose.
-   **Production-Ready**: Uses Gunicorn as a WSGI server for robustness.

## Prerequisites

-   Docker and Docker Compose installed.
-   A running Transmission instance.
-   An existing external Docker network that both this service and your Transmission container can connect to.

## Installation

### 1. Clone the Repository

Clone this repository to your local machine:
```bash
git clone https://github.com/garnajee/transmission-auto-toggle-torrent.git
cd transmission-auto-toggle-torrent
```

### 2. Configure the Environment

Create a `.env` file in the root of the project directory. You can copy the example file to start:
```bash
cp .env.example .env
```

Now, edit the `.env` file with your Transmission RPC details and tracker url.

**Important**: The `TR_IP` variable should be set to the **container name** of your Transmission instance (e.g., `transmission`, `transmission-docker`, etc.).

### 3. Configure Docker Networking

This service needs to communicate with your Transmission container. The recommended way is to connect both to the same user-defined Docker network.

In this project's `docker-compose.yml`, the service is configured to connect to an external network named `custom-network`.

```yaml
# docker-compose.yml (snippet)

services:
  transmission-manager:
    # ...
    networks:
      - custom-network # This should match your network name

networks:
  custom-network:
    external: true # Declares that the network is created elsewhere
```

**Action Required**:
1.  Find the name of the network your Transmission container is connected to. You can find this in your Transmission's `docker-compose.yml` file or by running `docker inspect <transmission_container_name>`.
2.  Update the `docker-compose.yml` in this project to use that network name. For example, if your network is named `media-network`, change `custom-network` to `media-network`.

### 4. Create the Configuration Directory

The application saves its settings (enabled/disabled state, tracker list) to a `config.json` file. To persist this file on your host machine, create a `config` directory before the first run.

```bash
mkdir config
```

### 5. Build and Run the Container

With the configuration in place, you can now build and start the service using Docker Compose.

```bash
# Build the image and start the container in detached mode
docker-compose up --build -d
```

The service will now be running.

## Usage

### Accessing the Web UI

Open your web browser and navigate to:
`http://<your_docker_host_ip>:8080`

If you are running Docker on the same machine, you can use `http://localhost:8080`.

From the UI, you can:
-   **Enable/Disable the Service**: Use the toggle button to start or stop the tracker management logic.
-   **Manage Trackers**: Add, edit, or remove tracker URLs in the text area. Enter one URL prefix per line. Click "Save Trackers" to apply changes.

### Viewing Logs

To monitor the script's activity and see which torrents are being processed, you can view the container's logs.

```bash
docker-compose logs -f
```

### Manual "Re-enable All"

In case you need to force-reactivate all trackers that the script has disabled, you can execute a special command. This is useful for cleanup, troubleshooting, or if you decide to stop using the service and want to restore all trackers to their original state.

This command runs a one-off task inside the running container to re-enable all trackers that have the `disabled-` prefix.

Run the following command from your terminal in the project's root directory:

```bash
docker-compose exec transmission-manager python app.py REENABLE_ALL
```

You can then monitor the progress by checking the container logs. You should see output indicating that the global re-activation has started and is processing the relevant torrents.

## Project Structure

```
.
├── docker-compose.yml   # Docker Compose configuration
├── Dockerfile           # Defines the Docker image
├── requirements.txt     # Python dependencies
├── .env.example         # Template for environment variables
├── app.py               # The main application (Flask server + background worker)
├── config/              # Host directory for persistent configuration (created by user)
└── README.md            # This file
```

