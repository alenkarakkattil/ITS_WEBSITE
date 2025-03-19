import datetime
import random

from flask import (Flask, jsonify, redirect, render_template, request, session,
                   url_for)

import bus_stop
import neonpost
from demand_forecast import predict_demand
from flask_session import Session
from journey_finder import (build_trip_stops, find_direct_trips,
                            find_multi_trip_journeys, get_next_departure,
                            get_stops_status_for_trip, load_combined_routes,
                            load_frequencies, load_gtfs_data,
                            load_transfers_matrix, seconds_to_time,
                            time_to_seconds)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)


@app.route('/get_nearest_stop', methods=['POST'])
def get_nearest_stop():
    data = request.get_json()
    lat = data.get("lat")
    lon = data.get("lon")
    if lat is None or lon is None:
        return jsonify({"error": "Missing latitude or longitude"}), 400

    result = neonpost.get_closest_bus_stop(lon, lat)
    if result:
        # Assuming result returns (bus_stop_name, bus_stop_long, bus_stop_lat, distance)
        return jsonify({
            "nearest_stop": result[0],
            "bus_stop_lon": result[1],
            "bus_stop_lat": result[2]
        })
    else:
        return jsonify({"nearest_stop": None})

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if neonpost.check_user_exists(username, password):
            session['username'] = username
            user_id=neonpost.get_user_id_by_credentials(username, password)
            if user_id:
                session['user_id']=user_id
            return redirect(url_for('dashboard'))
        else:
            return "Invalid login credentials"
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', username=session['username'])

@app.route('/inside_bus')
def inside_bus():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('inside_bus.html', bus_stops=bus_stop.bus_stops)

@app.route('/outside_bus')
def outside_bus():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('outside_bus.html', bus_stops=bus_stop.bus_stops)

@app.route('/submit_outside_bus', methods=['POST'])
def submit_outside_bus():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    # Retrieve user input from the form.
    start_stop = request.form.get('start_stop')
    dest_stop = request.form.get('end_stop')
    session['user_start_stop'] = start_stop
    session['user_end_stop'] = dest_stop

    # Load GTFS data and related structures.
    stops_df, stop_times_df, trips_df = load_gtfs_data()
    trip_stops = build_trip_stops(stops_df, stop_times_df)
    transfers_map = load_transfers_matrix("transfers_matrix.xlsx", sheet_name="TransfersMatrix")
    frequencies_df = load_frequencies()
    route_map = load_combined_routes()
    
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    
    # Find direct (single) trips and multi-trip journeys.
    direct = find_direct_trips(trip_stops, start_stop, dest_stop)
    multi = find_multi_trip_journeys(trip_stops, transfers_map, start_stop, dest_stop)
    
    results = []
    
    # Process direct trips.
    for d in direct:
        trip_id = d["trip_id"]
        scheduled_dep = d["stops"][0].get("departure_time")
        next_dep = get_next_departure(trip_id, current_time, frequencies_df)
        diff = (time_to_seconds(next_dep) - time_to_seconds(scheduled_dep)) if (scheduled_dep and next_dep) else 0
        adj_start_time = seconds_to_time(time_to_seconds(d["stops"][0].get("departure_time")) + diff)
        adj_end_time = seconds_to_time(time_to_seconds(d["stops"][-1].get("arrival_time")) + diff)
        elapsed_seconds = time_to_seconds(adj_end_time) - time_to_seconds(adj_start_time)
        elapsed_time = seconds_to_time(elapsed_seconds) if elapsed_seconds is not None else ""
        
        original_route_name = route_map.get(trip_id.strip().lower(), "Unknown")
        parts = [p.strip() for p in original_route_name.split("↔")]
        if len(parts) == 2:
            if start_stop.lower() == parts[1].lower():
                adjusted_route_name = f"{parts[1]} ↔ {parts[0]}"
            else:
                adjusted_route_name = original_route_name
        else:
            adjusted_route_name = original_route_name
        
        adjusted_stops = []
        for stop in d["stops"]:
            new_stop = stop.copy()
            if new_stop.get("departure_time"):
                new_stop["departure_time"] = seconds_to_time(time_to_seconds(new_stop["departure_time"]) + diff)
            if new_stop.get("arrival_time"):
                new_stop["arrival_time"] = seconds_to_time(time_to_seconds(new_stop["arrival_time"]) + diff)
            adjusted_stops.append(new_stop)
        
        results.append({
            "journey_type": "single",
            "route_long_name": adjusted_route_name,
            "start_stop": adjusted_stops[0]["stop_name"],
            "start_stop_time": adj_start_time,
            "end_stop": adjusted_stops[-1]["stop_name"],
            "end_stop_time": adj_end_time,
            "trip_ids": [trip_id],
            "distance": f"{d['distance']:.2f}",
            "cost": f"{d['cost']:.2f}",
            "elapsed": elapsed_time,
            "stops": adjusted_stops
        })
    
    # Process multi-trip journeys.
    for mj in multi:
        try:
            tripA, tripB = mj["trip_ids"]
            leg1 = mj["leg1"]["stops"]
            leg2 = mj["leg2"]["stops"]
            # Skip if leg data is missing.
            if not leg1 or not leg2:
                continue
            
            base_dep_leg1 = mj["leg1"]["base_dep"]
            next_dep_leg1 = get_next_departure(tripA, current_time, frequencies_df)
            diff1 = (time_to_seconds(next_dep_leg1) - time_to_seconds(base_dep_leg1)) if (base_dep_leg1 and next_dep_leg1) else 0
            adj_start_time = seconds_to_time(time_to_seconds(leg1[0].get("departure_time")) + diff1)
            transfer_time = seconds_to_time(time_to_seconds(leg1[-1].get("arrival_time")) + diff1)
            
            base_dep_leg2 = mj["leg2"]["base_dep"]
            next_dep_leg2 = get_next_departure(tripB, transfer_time, frequencies_df)
            diff2 = (time_to_seconds(next_dep_leg2) - time_to_seconds(base_dep_leg2)) if (base_dep_leg2 and next_dep_leg2) else 0
            adj_end_time = seconds_to_time(time_to_seconds(leg2[-1].get("arrival_time")) + diff2)
            
            elapsed_seconds = time_to_seconds(adj_end_time) - time_to_seconds(adj_start_time)
            elapsed_time = seconds_to_time(elapsed_seconds) if elapsed_seconds is not None else ""
            
            orig_routeA = route_map.get(tripA.strip().lower(), "Unknown")
            partsA = [p.strip() for p in orig_routeA.split("↔")]
            if len(partsA) == 2:
                if start_stop.lower() == partsA[1].lower():
                    adjusted_routeA = f"{partsA[1]} ↔ {partsA[0]}"
                else:
                    adjusted_routeA = orig_routeA
            else:
                adjusted_routeA = orig_routeA

            orig_routeB = route_map.get(tripB.strip().lower(), "Unknown")
            partsB = [p.strip() for p in orig_routeB.split("↔")]
            if len(partsB) == 2:
                if dest_stop.lower() == partsB[0].lower():
                    adjusted_routeB = f"{partsB[1]} ↔ {partsB[0]}"
                else:
                    adjusted_routeB = orig_routeB
            else:
                adjusted_routeB = orig_routeB

            # Build leg1_clean: Include stops from leg1 until reaching the transfer stop.
            leg1_clean = []
            for stop in leg1:
                leg1_clean.append(stop)
                if stop["stop_name"].strip().lower() == mj["transfer_stop"].strip().lower():
                    break

            # Build leg2_clean: Include stops from leg2 after the transfer stop.
            leg2_clean = []
            transfer_found = False
            for stop in leg2:
                if transfer_found:
                    leg2_clean.append(stop)
                if stop["stop_name"].strip().lower() == mj["transfer_stop"].strip().lower():
                    transfer_found = True

            # Adjust timings for leg1_clean using diff1.
            leg1_adjusted = []
            for stop in leg1_clean:
                new_stop = stop.copy()
                if new_stop.get("departure_time"):
                    new_stop["departure_time"] = seconds_to_time(time_to_seconds(new_stop["departure_time"]) + diff1)
                if new_stop.get("arrival_time"):
                    new_stop["arrival_time"] = seconds_to_time(time_to_seconds(new_stop["arrival_time"]) + diff1)
                leg1_adjusted.append(new_stop)

            # Adjust timings for leg2_clean using diff2.
            leg2_adjusted = []
            for stop in leg2_clean:
                new_stop = stop.copy()
                if new_stop.get("departure_time"):
                    new_stop["departure_time"] = seconds_to_time(time_to_seconds(new_stop["departure_time"]) + diff2)
                if new_stop.get("arrival_time"):
                    new_stop["arrival_time"] = seconds_to_time(time_to_seconds(new_stop["arrival_time"]) + diff2)
                leg2_adjusted.append(new_stop)
            
            # Only add multi-trip result if we have valid adjusted stops.
            if not leg1_adjusted or not leg2_adjusted:
                continue

            results.append({
                "journey_type": "multi",
                "route_long_name_leg1": adjusted_routeA,
                "route_long_name_leg2": adjusted_routeB,
                "start_stop": leg1_adjusted[0]["stop_name"],
                "start_stop_time": adj_start_time,
                "transfer_stop": leg1_adjusted[-1]["stop_name"],
                "transfer_stop_time": transfer_time,
                "end_stop": leg2_adjusted[-1]["stop_name"],
                "end_stop_time": adj_end_time,
                "trip_ids": [tripA, tripB],
                "distance": f"{mj['distance']:.2f}",
                "cost": f"{mj['cost']:.2f}",
                "elapsed": elapsed_time,
                "stops_leg1": leg1_adjusted,
                "stops_leg2": leg2_adjusted
            })
            
            # Store the transfer stop in the session for multi-trip journeys.
            session['transfer_stop'] = leg1_adjusted[-1]["stop_name"]
        except Exception as e:
            print("Error processing multi-journey route:", e)
            continue

    session['routes'] = results
    return render_template("simple_results.html", routes=results)

@app.route('/simple_results')
def simple_results():
    if 'routes' not in session:
        return redirect(url_for('outside_bus'))
    return render_template("simple_results.html", routes=session['routes'])


@app.route('/route_details/<int:route_index>')
def route_details(route_index):
    if 'routes' not in session:
        return redirect(url_for('outside_bus'))
    routes = session['routes']
    if route_index < 0 or route_index >= len(routes):
        return redirect(url_for('outside_bus'))
    selected_route = routes[route_index]
    return render_template("route_details.html", route=selected_route)

@app.route('/submit_inside_bus', methods=['POST'])
def submit_inside_bus():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    start_stop = request.form.get('start_stop')
    end_stop = request.form.get('end_stop')
    
    # Load data and build structures
    stops_df, stop_times_df, trips_df = load_gtfs_data()
    trip_stops = build_trip_stops(stops_df, stop_times_df)
    transfers_map = load_transfers_matrix("transfers_matrix.xlsx", sheet_name="TransfersMatrix")
    frequencies_df = load_frequencies()
    route_map = load_combined_routes()
    
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    
    # Find direct and multi-trip journeys
    direct = find_direct_trips(trip_stops, start_stop, end_stop)
    multi = find_multi_trip_journeys(trip_stops, transfers_map, start_stop, end_stop)
    
    results = []
    
    # Process direct trips: only store the trip_id.
    for d in direct:
        trip_id = d["trip_id"]
        results.append({
            "journey_type": "single",
            "trip_ids": [trip_id]
        })
    
    # Process multi-trip journeys: store both trip ids.
    for mj in multi:
        tripA, tripB = mj["trip_ids"]
        results.append({
            "journey_type": "multi",
            "trip_ids": [tripA, tripB]
        })
    
    session['routes'] = results
    return render_template("inside_bus_results.html", routes=results)


@app.route('/inside_bus_trip_details/<int:route_index>')
def inside_bus_trip_details(route_index):
    if 'routes' not in session:
        return redirect(url_for('inside_bus'))
    routes = session['routes']
    if route_index < 0 or route_index >= len(routes):
        return redirect(url_for('inside_bus'))
    selected_route = routes[route_index]
    # For now, render a blank/placeholder page.
    return render_template("inside_bus_trip_details.html", route=selected_route)


@app.route('/track_bus/<trip_id>')
def track_bus(trip_id):
    # Check if a bus for this trip exists.
    if not neonpost.check_bus_exists(trip_id):
        return "No bus available for tracking for this trip.", 404

    # Retrieve the bus_id associated with the trip_id.
    bus_id = neonpost.get_bus_id_by_trip(trip_id)
    if not bus_id:
        return "Bus ID could not be retrieved.", 404

    # Retrieve user-submitted start and end stops from the session.
    # These should be stored in the /submit_outside_bus route.
    user_start_stop = session.get('user_start_stop')
    user_end_stop = session.get('user_end_stop')

    # Determine which leg is being tracked using a query parameter.
    # For a single journey (or if no 'leg' parameter is provided):
    #    tracking_start_stop = user_start_stop
    #    tracking_end_stop = user_end_stop
    # For multi-journey trips:
    #    Leg 1: tracking_start_stop = user_start_stop, tracking_end_stop = transfer_stop
    #    Leg 2: tracking_start_stop = transfer_stop, tracking_end_stop = user_end_stop
    leg = request.args.get('leg', 'single')  # Default to 'single' if not provided.
    if leg == '1':
        tracking_start_stop = user_start_stop
        tracking_end_stop = session.get('transfer_stop', user_end_stop)
    elif leg == '2':
        tracking_start_stop = session.get('transfer_stop', user_start_stop)
        tracking_end_stop = user_end_stop
    else:
        tracking_start_stop = user_start_stop
        tracking_end_stop = user_end_stop

    # Optionally, you can also pass the original user_start_stop and user_end_stop
    # to display them on the tracking page if needed.
    return render_template("track_bus.html",
                           bus_id=bus_id,
                           trip_id=trip_id,
                           user_start_stop=user_start_stop,
                           user_end_stop=user_end_stop,
                           tracking_start_stop=tracking_start_stop,
                           tracking_end_stop=tracking_end_stop)



@app.route('/get_last_location', methods=['POST'])
def get_last_location():
    data = request.get_json()
    bus_id = data.get("bus_id")
    if not bus_id:
        return jsonify({"error": "Missing bus_id"}), 400

    try:
        result = neonpost.get_last_bus_location(bus_id)
        if result:
            latitude, longitude = result
            return jsonify({
                "bus_id": bus_id,
                "latitude": latitude,
                "longitude": longitude
            })
        else:
            return jsonify({"error": "No location found for the specified bus ID."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.route('/get_stops_status', methods=['POST'])
def get_stops_status():
    data = request.get_json()
    trip_id = data.get("trip_id")
    current_lat = data.get("lat")
    current_lon = data.get("lon")
    if not all([trip_id, current_lat, current_lon]):
        return jsonify({"error": "Missing parameters"}), 400
    stops_status = get_stops_status_for_trip(trip_id, float(current_lat), float(current_lon))
    return jsonify(stops_status)





@app.route('/live_bus')
def live_bus():
    if 'username' not in session:
        return redirect(url_for('login'))
    live_bus_ids = neonpost.get_live_bus_ids()  # Retrieve live bus IDs
    return render_template('live_bus.html', live_bus_ids=live_bus_ids)





@app.route('/recommendation', methods=['GET'])
def recommendation():
    if 'username' not in session:
        return redirect(url_for('login'))
    # Render a form for the user to input forecast details
    return render_template('recommendation.html')


@app.route('/predict_demand', methods=['POST'])
def predict_demand_route():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    # Retrieve form inputs
    time_of_day = request.form.get('time_of_day')
    day_of_week = int(request.form.get('day_of_week'))
    is_weekend = int(request.form.get('is_weekend'))
    
    # Call the prediction function
    prediction = predict_demand(time_of_day, day_of_week, is_weekend)
    
    # Render the result template and pass the prediction
    return render_template('prediction_result.html', prediction=prediction, 
                           time_of_day=time_of_day, day_of_week=day_of_week, is_weekend=is_weekend)


@app.route('/get_dashboard_status', methods=['GET'])
def get_dashboard_status():
    activeBusCount = neonpost.get_active_bus_count()
    currentUsers = neonpost.get_current_users_count()
    return jsonify({
        'activeBusCount': activeBusCount,
        'currentUsers': currentUsers
    })

def get_travel_history(username):
    # Replace the following with your actual database query.
    # Here we use dummy data for illustration.
    return [
        {"date": "2023-05-01", "route": "Route A", "from": "Stop 1", "to": "Stop 5"},
        {"date": "2023-04-25", "route": "Route B", "from": "Stop 3", "to": "Stop 8"},
        # Add more history entries as needed
    ]



@app.route('/profile')
def profile():
    # Assume the user_id is stored in the session after login
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/login')  # or show an error
    
    user = neonpost.get_user_details(user_id)
    if not user:
        return "User not found", 404

    return render_template('profile.html', user=user)


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
