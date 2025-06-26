#!/usr/bin/env python3
# app.py

import os
import sys
import time
import json
import threading
from collections import defaultdict
from dotenv import load_dotenv
from transmission_rpc import Client
from flask import Flask, jsonify, request, render_template_string

load_dotenv()

# used to store the state and parameters of the app dynamically,
# so that they can be read and modified by the web interface without having to restart the container.
CONFIG_FILE = "config.json"

app = Flask(__name__)

# --- Configuration management (via JSON file) ---
def load_config():
    """Loads the configuration from config.json or creates one by default."""
    if not os.path.exists(CONFIG_FILE):
        print(f "Configuration file '{CONFIG_FILE}' not found. Creation...")
        default_trackers = [url.strip() for url in os.getenv("TARGET_TRACKERS", "").split(',') if url.strip()]
        config = {
            "enabled": True,
            "target_trackers": default_trackers
        }
        save_config(config)
        return config
    
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(config):
    """Save configuration in config.json."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

# --- TransmissionManager class ---

class TransmissionManager:
    """Manages the connection and targeted actions with a Transmission instance."""
    def __init__(self):
        self.client = self._connect()
        self.prefix = "disabled-"

    def _connect(self):
        """Establishes a connection to the Transmission RPC server."""
        try:
            # Important: Make sure that TR_IP is the name of the transmission container
            return Client(
                host=os.getenv("TR_IP"),
                port=int(os.getenv("TR_PORT", 9091)),
                username=os.getenv("TR_USERNAME"),
                password=os.getenv("TR_PASSWORD")
            )
        except Exception as e:
            print(f"Transmission connection error: {e}")
            return None

    def _change_trackers(self, torrent_id: int, new_tracker_list: list[list[str]]):
        if not self.client: return
        self.client.change_torrent(ids=[torrent_id], tracker_list=new_tracker_list)

    def _is_tracker_targeted(self, announce_url: str, target_prefixes: list[str]) -> bool:
        clean_url = announce_url.replace(f"://{self.prefix}", "://")
        return any(clean_url.startswith(target) for target in target_prefixes)

    def process_torrents(self, target_trackers: list[str]):
        if not self.client:
            print("Client not connected. Cannot process torrents.")
            return

        all_torrents = self.client.get_torrents()
        print(f"Vérification de {len(all_torrents)} torrents...")
        
        torrents_to_disable, torrents_to_enable = [], []

        for torrent in all_torrents:
            if not any(self._is_tracker_targeted(tracker.announce, target_trackers) for tracker in torrent.trackers):
                continue

            needs_change = False
            is_complete = torrent.percent_done >= 1.0

            if not is_complete: # Torrent not complete -> we want to disable it
                if any(self._is_tracker_targeted(t.announce, target_trackers) and f"://{self.prefix}" not in t.announce for t in torrent.trackers):
                    needs_change = True
                    torrents_to_disable.append(torrent)
            else: # Torrent complete -> we want to reactivate
                if any(self._is_tracker_targeted(t.announce, target_trackers) and f"://{self.prefix}" in t.announce for t in torrent.trackers):
                    needs_change = True
                    torrents_to_enable.append(torrent)
        
        if torrents_to_disable:
            print(f"Deactivation for IDs: {[t.id for t in torrents_to_disable]}")
            self._toggle_target_trackers(torrents_to_disable, target_trackers, disable=True)

        if torrents_to_enable:
            print(f"Reactivation for IDs: {[t.id for t in torrents_to_enable]}")
            self._toggle_target_trackers(torrents_to_enable, target_trackers, disable=False)
            
        print("Verification run complete.")

    def _toggle_target_trackers(self, torrents: list, target_trackers: list[str], disable: bool):
        for torrent in torrents:
            new_tiers = defaultdict(list)
            for tracker in torrent.trackers:
                original_url = tracker.announce
                if self._is_tracker_targeted(original_url, target_trackers):
                    if disable and f"://{self.prefix}" not in original_url:
                        new_tiers[tracker.tier].append(original_url.replace("://", f"://{self.prefix}"))
                    elif not disable and f"://{self.prefix}" in original_url:
                        new_tiers[tracker.tier].append(original_url.replace(f"://{self.prefix}", "://"))
                    else:
                        new_tiers[tracker.tier].append(original_url)
                else:
                    new_tiers[tracker.tier].append(original_url)
            
            final_tracker_list = [new_tiers[tier] for tier in sorted(new_tiers.keys())]
            self._change_trackers(torrent.id, final_tracker_list)

    def reenable_all_trackers(self):
        """Emergency function to reactivate everything"""
        if not self.client: return
        print("Launch global tracker reactivation...")
        all_torrents = self.client.get_torrents()
        for torrent in all_torrents:
            if any(f"://{self.prefix}" in t.announce for t in torrent.trackers):
                print(f"Reactivate trackers for torrent {torrent.id} ({torrent.name})")
                new_tiers = defaultdict(list)
                for tracker in torrent.trackers:
                    new_tiers[tracker.tier].append(tracker.announce.replace(f"://{self.prefix}", "://"))
                self._change_trackers(torrent.id, [new_tiers[tier] for tier in sorted(new_tiers.keys())])
        print("Global reactivation complete.")

# --- Background worker ---

def worker_loop():
    """The monitoring loop, which runs in a separate thread."""
    manager = TransmissionManager()
    check_interval = int(os.getenv("CHECK_INTERVAL", 60))
    
    # Special verification for REENABLE_ALL at every startup if asked
    if len(sys.argv) > 1 and sys.argv[1] == 'REENABLE_ALL':
        manager.reenable_all_trackers()
        # we don't exit, webserver must continue to run
        print("Single reactivation completed. Script continues in server mode.")


    while True:
        try:
            config = load_config()
            if not config.get('enabled', False):
                print("The service is disabled from the web interface. Paused.")
                time.sleep(check_interval)
                continue

            if not config.get('target_trackers'):
                print("No target tracker configured in the web interface. Paused.")
                time.sleep(check_interval)
                continue

            print("\n--- New worker run ---")
            manager.process_torrents(config['target_trackers'])
        
        except Exception as e:
            print(f"An unexpected error has occurred in the worker: {e}")
            print("Attempting to reconnect...")
            manager = TransmissionManager() # Recreates the connection

        print(f"Next check in {check_interval} seconds.")
        time.sleep(check_interval)

# --- Web Interface (Flask) ---

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Transmission Tracker Manager</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; background: #f4f4f4; color: #333; max-width: 800px; margin: 20px auto; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.05); }
        h1, h2 { color: #1a1a1a; }
        .container { background: white; padding: 25px; border-radius: 5px; }
        .status { margin-bottom: 20px; font-size: 1.2em; }
        .status-on { color: #28a745; font-weight: bold; }
        .status-off { color: #dc3545; font-weight: bold; }
        label { font-weight: bold; display: block; margin-bottom: 10px; }
        textarea { width: 98%; height: 150px; padding: 10px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; }
        button { background: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; font-size: 1em; margin-top: 10px; }
        button:hover { background: #0056b3; }
        .toggle-btn { background-color: #6c757d; }
        .message { margin-top: 15px; padding: 10px; border-radius: 4px; display: none; }
        .message.success { background: #d4edda; color: #155724; }
        .message.error { background: #f8d7da; color: #721c24; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Transmission Tracker Manager</h1>
        
        <div class="status">
            Service Status: <span id="status-text">Loading...</span>
        </div>

        <form id="toggle-form">
            <button type="submit" class="toggle-btn" id="toggle-button">Enable/Disable</button>
        </form>

        <hr style="margin: 30px 0;">

        <h2>Target Trackers</h2>
        <p>Enter one URL per line. The script will disable these trackers on incomplete torrents and re-enable them at 100%.</p>
        <form id="trackers-form">
            <label for="trackers">Tracker prefixes to monitor:</label>
            <textarea id="trackers" name="trackers"></textarea>
            <button type="submit">Save Trackers</button>
        </form>
        
        <div id="message-box" class="message"></div>
    </div>

    <script>
        const statusText = document.getElementById('status-text');
        const toggleButton = document.getElementById('toggle-button');
        const trackersTextarea = document.getElementById('trackers');
        const toggleForm = document.getElementById('toggle-form');
        const trackersForm = document.getElementById('trackers-form');
        const messageBox = document.getElementById('message-box');

        let currentState = {};

        function showMessage(text, type = 'success') {
            messageBox.textContent = text;
            messageBox.className = `message ${type}`;
            messageBox.style.display = 'block';
            setTimeout(() => { messageBox.style.display = 'none'; }, 3000);
        }

        async function fetchConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();
                currentState = config;
                updateUI();
            } catch (error) {
                console.error('Error loading config:', error);
                statusText.textContent = 'Connection Error';
                statusText.className = 'status-off';
            }
        }

        function updateUI() {
            if (currentState.enabled) {
                statusText.textContent = 'Enabled';
                statusText.className = 'status-on';
                toggleButton.textContent = 'Disable Service';
            } else {
                statusText.textContent = 'Disabled';
                statusText.className = 'status-off';
                toggleButton.textContent = 'Enable Service';
            }
            trackersTextarea.value = currentState.target_trackers.join('\\n');
        }

        toggleForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const newConfig = { ...currentState, enabled: !currentState.enabled };
            try {
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(newConfig)
                });
                if (!response.ok) throw new Error('Server error');
                currentState = await response.json();
                updateUI();
                showMessage('Status saved successfully!');
            } catch (error) {
                showMessage('Error during save.', 'error');
            }
        });

        trackersForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const trackers = trackersTextarea.value.split('\\n').map(t => t.trim()).filter(t => t);
            const newConfig = { ...currentState, target_trackers: trackers };
            try {
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(newConfig)
                });
                 if (!response.ok) throw new Error('Server error');
                currentState = await response.json();
                updateUI();
                showMessage('Tracker list saved!');
            } catch (error) {
                showMessage('Error during save.', 'error');
            }
        });

        // Load config on startup
        fetchConfig();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Serves as the main HTML page."""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """API for reading and writing the configuration."""
    if request.method == 'POST':
        new_config = request.json
        if 'enabled' in new_config and isinstance(new_config['enabled'], bool):
            current_config = load_config()
            current_config['enabled'] = new_config['enabled']
            save_config(current_config)

        if 'target_trackers' in new_config and isinstance(new_config['target_trackers'], list):
            current_config = load_config()
            current_config['target_trackers'] = [str(t) for t in new_config['target_trackers']]
            save_config(current_config)
        
    return jsonify(load_config())

# Start the worker in a separate thread
print("Starting background worker thread...")
worker_thread = threading.Thread(target=worker_loop)
worker_thread.daemon = True  # Allows the main program to exit even if the thread is running
worker_thread.start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)

