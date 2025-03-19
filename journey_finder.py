import pandas as pd
import ast
import math
from collections import defaultdict

# --- GTFS Data Loading and Processing ---

def load_gtfs_data():
    """
    Load GTFS data from text files.
    Returns three DataFrames: stops, stop_times, trips.
    """
    stops = pd.read_csv("combined_stops.txt")
    stop_times = pd.read_csv("combined_stop_times.txt")
    trips = pd.read_csv("combined_trips.txt")
    return stops, stop_times, trips

def build_trip_stops(stops_df, stop_times_df):
    """
    Merge stops and stop_times data, order by stop_sequence,
    and build a dictionary keyed by trip_id.
    """
    merged = stop_times_df.merge(
        stops_df[["stop_id", "stop_name", "stop_lat", "stop_lon"]],
        on="stop_id", how="left"
    )
    merged["stop_sequence"] = merged["stop_sequence"].astype(int)
    merged = merged.sort_values(["trip_id", "stop_sequence"]).reset_index(drop=True)
    trip_stops = {}
    for trip_id, group in merged.groupby("trip_id"):
        trip_stops[trip_id] = group.to_dict("records")
    return trip_stops

def load_transfers_matrix(excel_file="transfers_matrix.xlsx", sheet_name="TransfersMatrix"):
    """
    Load transfers matrix from an Excel file.
    Returns a nested dictionary mapping tripA -> tripB -> list of transfer stops.
    """
    df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
    col_trip_ids = df.iloc[0, 1:].tolist()
    row_trip_ids = df.iloc[1:, 0].tolist()
    transfers_map = defaultdict(lambda: defaultdict(list))
    for i, row_trip in enumerate(row_trip_ids, start=1):
        for j, col_trip in enumerate(col_trip_ids, start=1):
            cell_value = df.iloc[i, j]
            if pd.isna(cell_value) or cell_value == "[]":
                transfers_map[row_trip][col_trip] = []
            else:
                try:
                    stops_list = ast.literal_eval(cell_value)
                    transfers_map[row_trip][col_trip] = stops_list if isinstance(stops_list, list) else []
                except:
                    transfers_map[row_trip][col_trip] = []
    return transfers_map

def load_frequencies():
    """
    Load frequencies from the GTFS frequencies file.
    """
    try:
        frequencies = pd.read_csv("combined_frequencies.txt")
    except Exception as e:
        print("Error loading frequencies.txt:", e)
        frequencies = pd.DataFrame()
    return frequencies

def load_combined_routes():
    """
    Load a mapping of trip_id to route_long_name from a file.
    """
    try:
        routes_df = pd.read_csv("combined_trip_names.txt")
        route_map = dict(zip(routes_df["trip_id"], routes_df["route_long_name"]))
        # Normalize keys to lowercase without extra whitespace.
        route_map = {k.strip().lower(): v.strip() for k, v in route_map.items()}
        return route_map
    except Exception as e:
        print("Error loading combined_trip_names.txt:", e)
        return {}

# --- Time Helpers ---

def time_to_seconds(t):
    """
    Convert a time string (HH:MM:SS) to seconds.
    """
    try:
        h, m, s = map(int, t.split(":"))
        return h * 3600 + m * 60 + s
    except Exception:
        return None

def seconds_to_time(sec):
    """
    Convert seconds to a time string (HH:MM:SS).
    """
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02}:{m:02}:{s:02}"

def get_next_departure(trip_id, current_time_str, frequencies_df):
    """
    For a given trip_id and current time (HH:MM:SS), determine the next departure time based on frequencies.
    """
    current_secs = time_to_seconds(current_time_str)
    freq_rows = frequencies_df[frequencies_df["trip_id"] == trip_id]
    if freq_rows.empty:
        return None
    for _, row in freq_rows.iterrows():
        start_secs = time_to_seconds(row["start_time"])
        end_secs = time_to_seconds(row["end_time"])
        headway = row["headway_secs"]
        if current_secs < start_secs:
            return row["start_time"]
        elif start_secs <= current_secs <= end_secs:
            elapsed = current_secs - start_secs
            intervals_passed = elapsed // headway
            next_dep_secs = start_secs + (intervals_passed + 1) * headway
            if next_dep_secs <= end_secs:
                return seconds_to_time(next_dep_secs)
    first_row = freq_rows.iloc[0]
    return first_row["start_time"]

# --- Distance Helpers ---

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle distance (in kilometers) between two points on the Earth's surface.
    """
    R = 6371  # Earth's radius in kilometers
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def calculate_distance_for_stops(stops):
    """
    Given a list of stops (each with stop_lat and stop_lon), compute the total distance (in km).
    """
    total_distance = 0.0
    for i in range(len(stops) - 1):
        lat1 = float(stops[i]["stop_lat"])
        lon1 = float(stops[i]["stop_lon"])
        lat2 = float(stops[i+1]["stop_lat"])
        lon2 = float(stops[i+1]["stop_lon"])
        total_distance += haversine_distance(lat1, lon1, lat2, lon2)
    return total_distance

# --- Journey Finding Functions ---

def find_direct_trips(trip_stops, start_stop_name, dest_stop_name):
    """
    Finds direct trips where the start stop appears before the destination stop.
    Returns a list of dicts containing trip_id, stops segment, distance, and cost.
    """
    results = []
    for trip_id, stops in trip_stops.items():
        stop_names_lc = [s["stop_name"].lower() for s in stops if s["stop_name"]]
        start_indices = [i for i, name in enumerate(stop_names_lc) if name == start_stop_name.lower()]
        dest_indices = [i for i, name in enumerate(stop_names_lc) if name == dest_stop_name.lower()]
        if start_indices and dest_indices:
            for start_idx in start_indices:
                for dest_idx in dest_indices:
                    if start_idx < dest_idx:
                        segment = stops[start_idx:dest_idx+1]
                        distance = calculate_distance_for_stops(segment)
                        cost = 10 + distance
                        results.append({
                            "trip_id": trip_id,
                            "stops": segment,
                            "distance": distance,
                            "cost": math.ceil(cost)
                        })
    return results

def find_multi_trip_journeys(trip_stops, transfers_map, start_stop_name, dest_stop_name):
    """
    Finds multi-trip journeys requiring a transfer. Returns a list of dictionaries containing:
      - trip_ids (for both legs),
      - transfer stop,
      - stops for leg1 and leg2,
      - total distance and cost.
    """
    results = []
    for tripA in trip_stops.keys():
        for tripB in trip_stops.keys():
            if tripA == tripB:
                continue
            possible_transfers = transfers_map[tripA][tripB]
            if not possible_transfers:
                continue
            stopsA = trip_stops[tripA]
            stopsB = trip_stops[tripB]
            stop_namesA_lc = [s["stop_name"].lower() for s in stopsA if s["stop_name"]]
            stop_namesB_lc = [s["stop_name"].lower() for s in stopsB if s["stop_name"]]
            start_indices_A = [i for i, name in enumerate(stop_namesA_lc) if name == start_stop_name.lower()]
            dest_indices_B = [i for i, name in enumerate(stop_namesB_lc) if name == dest_stop_name.lower()]
            if not start_indices_A or not dest_indices_B:
                continue
            for t_stop in possible_transfers:
                t_stop_lc = t_stop.lower()
                t_indices_A = [i for i, name in enumerate(stop_namesA_lc) if name == t_stop_lc]
                t_indices_B = [i for i, name in enumerate(stop_namesB_lc) if name == t_stop_lc]
                if not t_indices_A or not t_indices_B:
                    continue
                for start_idx in start_indices_A:
                    for t_idxA in t_indices_A:
                        if t_idxA <= start_idx:
                            continue
                        for t_idxB in t_indices_B:
                            for dest_idx in dest_indices_B:
                                if t_idxB >= dest_idx:
                                    continue
                                leg1 = stopsA[start_idx:t_idxA+1]
                                leg2 = stopsB[t_idxB:dest_idx+1]
                                distance_leg1 = calculate_distance_for_stops(leg1)
                                distance_leg2 = calculate_distance_for_stops(leg2)
                                total_distance = distance_leg1 + distance_leg2
                                cost = 10 + math.ceil(total_distance)
                                results.append({
                                    "trip_ids": [tripA, tripB],
                                    "transfer_stop": t_stop,
                                    "leg1": {
                                        "stops": leg1,
                                        "base_dep": leg1[0].get("departure_time")
                                    },
                                    "leg2": {
                                        "stops": leg2,
                                        "base_dep": leg2[0].get("departure_time")
                                    },
                                    "distance": total_distance,
                                    "cost": cost
                                })
    return results

# --- New Function: Get Stop Status Based on Current Location ---

def get_stops_status_for_trip(trip_id, current_lat, current_lon, threshold=50):
    """
    For a given trip_id and current bus location (current_lat, current_lon),
    load the GTFS data, build the list of stops for the trip, and mark each stop with a
    'passed' flag (True/False). The function determines the stop closest to the current location
    (in meters), then marks all stops before that index as passed. Additionally, if the bus is within
    the 'threshold' (in meters) of a stop, that stop is also marked as passed.
    
    Parameters:
      trip_id: The GTFS trip identifier.
      current_lat, current_lon: The current bus latitude and longitude.
      threshold: Distance (in meters) to consider a stop as passed.
      
    Returns:
      A list of stop dictionaries for the trip, each with an extra key 'passed'.
    """
    try:
        stops_df, stop_times_df, trips_df = load_gtfs_data()
        trip_stops = build_trip_stops(stops_df, stop_times_df)
        if trip_id not in trip_stops:
            print("Trip ID not found in GTFS data.")
            return []
        
        stops = trip_stops[trip_id]
        closest_index = None
        min_distance = float('inf')
        
        # Determine the index of the stop closest to the current bus location.
        for idx, stop in enumerate(stops):
            try:
                stop_lat = float(stop['stop_lat'])
                stop_lon = float(stop['stop_lon'])
            except Exception as e:
                continue
            distance = haversine_distance(current_lat, current_lon, stop_lat, stop_lon) * 1000  # in meters
            if distance < min_distance:
                min_distance = distance
                closest_index = idx
        
        # Mark stops as passed: if their index is less than the closest index,
        # or if the current location is within the threshold distance.
        for idx, stop in enumerate(stops):
            try:
                stop_lat = float(stop['stop_lat'])
                stop_lon = float(stop['stop_lon'])
                distance = haversine_distance(current_lat, current_lon, stop_lat, stop_lon) * 1000
            except Exception as e:
                distance = float('inf')
            if idx < closest_index or distance <= threshold:
                stop['passed'] = True
            else:
                stop['passed'] = False
        return stops
    except Exception as e:
        print("Error in get_stops_status_for_trip:", e)
        return []
