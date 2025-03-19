import pickle
import pandas as pd

def predict_demand(time_of_day, day_of_week, is_weekend, model_path='demand_forecast_model.pkl'):
    """
    Load the pickled demand forecast model and predict the number of users.
    
    Parameters:
      time_of_day (str): Time in HH:MM or HH:MM:SS format.
      day_of_week (int): Day of week (e.g., 0=Monday, ... 6=Sunday).
      is_weekend (int): 1 if weekend, 0 otherwise.
      
    Returns:
      int: Predicted number of users.
    """
    # If the time string doesn't include seconds, add ":00"
    if time_of_day.count(':') == 1:
        time_of_day += ":00"
        
    # Load the model
    with open(model_path, 'rb') as file:
        loaded_model = pickle.load(file)
    
    # Preprocess the input: convert time to hour
    hour = pd.to_datetime(time_of_day, format='%H:%M:%S').hour
    input_data = [[hour, day_of_week, is_weekend]]
    
    # Predict and return the result
    prediction = loaded_model.predict(input_data)[0]
    return int(prediction)
