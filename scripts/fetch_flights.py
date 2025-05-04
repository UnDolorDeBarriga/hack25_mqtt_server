import requests
import datetime
import json
now = datetime.datetime.now()
from bs4 import BeautifulSoup
from datetime import datetime
from time import sleep
import os
import re
import time
import paho.mqtt.client as mqtt

def sanitize_folder_name(name: str) -> str:
    """
    Replaces invalid folder name characters with hyphens or removes them.

    Invalid characters (Windows): \ / : * ? " < > |
    Also strips leading/trailing whitespace and dots.
    """
    # Replace invalid characters with a hyphen
    sanitized = re.sub(r'[\\/:*?"<>|]', '-', name)
    # Remove control characters and other unwanted symbols
    sanitized = re.sub(r'[\x00-\x1f]', '', sanitized)
    # Strip leading/trailing whitespace and dots
    sanitized = sanitized.strip().strip('.')
    return sanitized

def invertir_ciudad(ciudad: str, traducir=False) -> str:
    nombre, codigo = ciudad.strip().rsplit(" ", 1)
    codigo = codigo.strip("()")

    if traducir:
        traducciones = {
            "Lisbon": "Lisboa",
            "Barcelona": "Barcelona",
            "Paris": "París",
            # Agrega más traducciones según necesites
        }
        nombre = traducciones.get(nombre, nombre)

    return f"({codigo}) {nombre}"


def get_next_flights():
    hora_str = now.strftime("%H:%M:%S")
    hora, min, _ = hora_str.split(":")
    hora = int(hora)
    min = int(min)

    i = hora//3
    if i > 6:
        i = 6

    url_b = "https://www.aeropuertobarcelona-elprat.com/cat/sortides_vols_aeroport_barcelona.html"
    times = ["0-3", "3-6", "6-9", "9-12", "12-15", "15-18", "18-21", "21-0", "0-3--1", "18-0--1"]
    #times = ["?t=0-3&a=", "?t=3-6&a=", "?t=6-9&a=", "?t=9-12&a=", "?t=12-15&a=", "?t=15-18&a=", "?t=18-21&a=", "?t=21-0&a=", "?t=0-3%2B1&a=", "?t=3-6%2B1&a="]

    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    times_check = []
    for offset in range(1):
        i=9
        index = (i + offset) % len(times)
        times_check.append(times[index])


    url="https://www.aeropuertobarcelona-elprat.com/cat/sortides_vols_aeroport_barcelona.html"
    flights = {}
    for time in times_check:
        response = requests.get(url,params={"t":time}, headers=headers)
        soup = BeautifulSoup(response.content, "html.parser")

        flight_records = soup.select("div.flightListRecord")
        print(len(flight_records))
        for record in flight_records:
            try:
                destination_raw = record.select_one("div.flightListOtherAirport").get_text(strip=True)
                time, destination_raw = destination_raw.split("-", 1)
                destination, airport = destination_raw.split("(")
                airport = airport.replace(")", "").strip()

                departure_status = record.select_one("div.flightListTimeStatus").get_text(strip=True).replace("·l","")
                flight_links = record.select("div.flightListFlightIDs a.flightListFlightIDLink")
                flight_numbers = [link.get_text(strip=True) for link in flight_links]
                file_name = sanitize_folder_name(flight_numbers[0])

                # Analizar estado y retraso (si existe)
                # Normalizar el texto de estado para facilitar parsing
                departure_status = record.select_one("div.flightListTimeStatus").get_text(strip=True).replace("·l", "l")

                # Detectar estado principal
                if "Retardat" in departure_status:
                    status = "Retardat"
                elif "Cancel·lat" in departure_status:
                    status = "Cancel·lat"
                elif "Programat" in departure_status:
                    status = "Programat"
                elif "Ha sortit" in departure_status:
                    status = "Ha sortit"
                else:
                    status = "Desconegut"

                # Buscar posible hora (retardo o salida)
                delay_match = re.search(r"(\d{2}:\d{2})", departure_status)
                delay = delay_match.group(1) if delay_match else None

                # Saltar vuelos desconocidos
                if status == "Desconegut":
                    continue

                flight_info = {
                    "flight_number": flight_numbers,
                    "destination": destination.strip(),
                    "airport": airport,
                    "time": time,
                    "departure_status": status,
                }
                if delay:
                    flight_info["delay"] = delay

                if status=="Desconegut":
                    print("Tralarero tralara")
                else:
                    flights[file_name] = flight_info
                    if len(flights)>45:
                        return flights
            except AttributeError:
                continue
            # flights_json = json.dumps(flights, indent=4, ensure_ascii=False)
    return flights

def update_changes(client, new_flights: dict, old_flights: dict):
    for flight_id, flight_data in new_flights.items():
        if old_flights.get(flight_id) != flight_data:
            topic = f"flights/{flight_id}"
            payload = json.dumps(flight_data, ensure_ascii=False)  # Asegúrate de convertir a JSON
            client.publish(topic, payload, retain=True)

def create_changes_dict(old_flights: dict, new_flights: dict):
    changes = {}

    for flight_id, old_data in old_flights.items():
        if flight_id not in new_flights:
            changes[flight_id] = None  # El vuelo ya no está, asignamos un payload vacío

    for flight_id, new_data in new_flights.items():
        if flight_id not in old_flights:
            changes[flight_id] = new_data  # Vuelo nuevo, lo agregamos con los datos del nuevo vuelo

    for flight_id, old_data in old_flights.items():
        if flight_id in new_flights and old_data != new_flights[flight_id]:
            changes[flight_id] = new_flights[flight_id]  # Vuelo existe en ambos y ha cambiado, lo actualizamos

    return changes

def create_changes_dict(old_flights: dict, new_flights: dict):
    changes = {}

    for flight_id, old_data in old_flights.items():
        if flight_id not in new_flights:
            changes[flight_id] = None  # O puedes dejarlo vacío si es necesario: changes[flight_id] = {}
        elif old_data != new_flights[flight_id]:
            changes[flight_id] = new_flights[flight_id]

    for flight_id, new_data in new_flights.items():
        if flight_id not in old_flights:
            changes[flight_id] = new_data

    return changes

def publish_flights_mqtt(client, flights: dict, broker_host="localhost", broker_port=1883, topic_prefix="flights/"):
    """
    Publishes each flight's data to a separate MQTT topic.

    :param flights: Dict of flights {flight_id: flight_data}
    :param broker_host: MQTT broker host (default 'localhost')
    :param broker_port: MQTT broker port (default 1883)
    :param topic_prefix: Prefix for MQTT topics
    """
    for flight_id, flight_data in flights.items():
        topic = f"{topic_prefix}{flight_id}"
        payload = json.dumps(flight_data, ensure_ascii=False)
        client.publish(topic, payload, retain=True)

def publish_obj_mqtt(client, data: list, broker_host="localhost", broker_port=1883, topic_prefix="flights/"):
    """
    Publishes each flight's data to a separate MQTT topic.

    :param flights: Dict of flights {flight_id: flight_data}
    :param broker_host: MQTT broker host (default 'localhost')
    :param broker_port: MQTT broker port (default 1883)
    :param topic_prefix: Prefix for MQTT topics
    """
    topic = f"{topic_prefix}"
    payload = json.dumps(data, ensure_ascii=False)
    client.publish(topic, payload, retain=True)

def connect(broker_host, broker_port):
    client = mqtt.Client()
    client.username_pw_set("admin","admin")
    client.connect(broker_host, broker_port)

    return client

def on_message(client, userdata, msg):
    flight_id = msg.topic.split("/")[-1]
    if msg.payload:
        try:
            flight_data = json.loads(msg.payload.decode('utf-8'))
            userdata[flight_id] = flight_data
        except json.JSONDecodeError:
            print(f"Error decoding JSON for topic {msg.topic}")

def load_existing_flights(client, old_flights, topic_prefix="flights/"):
    client.user_data_set(old_flights)
    client.on_message = on_message
    client.subscribe(f"{topic_prefix}#")
    client.loop_start()
    time.sleep(2)  # Espera para recibir todos los mensajes
    client.loop_stop()

if __name__ == "__main__":
    news=[
        {
            "Title": "Blackout",
            "Time": "17:00",
            "Description": "General blackout in Barcelona–El Prat"
        },
        {
            "Title": "Authorities",
            "Time": "18:00",
            "Description": "Authorities are coming to the airport"
        }
    ]
    client = connect("mqtt", 1883)
    publish_obj_mqtt(client, news, topic_prefix="news")
    client.disconnect()
    while True:
        try:
            client = connect("mqtt", 1883)
            old_flights = {}
            load_existing_flights(client, old_flights, "flights/")
            new_flights = get_next_flights()
            changes = create_changes_dict(old_flights, new_flights)
            publish_flights_mqtt(client, changes, topic_prefix="flights/")
            client.disconnect()
        except Exception as e:
            print(f"Error occurred: {e}")
        time.sleep(30)
