import telebot
from telebot import types
import requests
import base64
from datetime import datetime
import pickle
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# The token for the Telegram bot
TOKEN = 'nope'
bot = telebot.TeleBot(TOKEN)

# A password for the bot
PASSWORD = 'luna'
# A dictionary to keep track of the state of each user
user_states = {}

# The API key for OpenAI
OPENAI_API_KEY = "nope"
# The path to the file containing the client secret for Google API
CLIENT_SECRET_FILE = 'credentials.json'
# The scopes for Google API
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
# The ID of the Google Sheets spreadsheet
SPREADSHEET_ID = 'nope'
# The name of the range in the Google Sheets spreadsheet
RANGE_NAME = 'Sheet1!A:G'

# Global variables to store the details of the receipt
store_name = ""
category = ""
total_price = ""
gst = "$0.00"
hst = "$0.00"
pst = "$0.00"
date = ""


def authenticate_google_api():
    """
    This function authenticates the Google API.

    It first checks if a file named 'token.pickle' exists. If it does, it loads the credentials from the file.
    If the file does not exist, or the credentials are invalid, it prompts the user to sign in and then saves the
    credentials to 'token.pickle' for future use.

    It then uses the credentials to build and return a service object for the Google Sheets API.
    """
    creds = None
    # Check if 'token.pickle' exists
    if os.path.exists('token.pickle'):
        # Check if 'token.pickle' is not empty
        if os.path.getsize('token.pickle') > 0:
            # Open 'token.pickle' and load the credentials
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
    # If the credentials are invalid, prompt the user to sign in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=8080)
        # Save the credentials for future use
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    # Build and return the service object
    service = build('sheets', 'v4', credentials=creds)
    return service


def append_data_to_sheet(service, values):
    """
    This function appends a row of data to the Google Sheets spreadsheet.

    It first creates a body with the data, then calls the Google Sheets API to append the data to the spreadsheet.
    It returns the row number where the data was written.
    """
    body = {'values': [values]}
    result = service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME,
        valueInputOption='USER_ENTERED', body=body, insertDataOption='INSERT_ROWS').execute()
    # Return the row number where the data was written
    return result['updates']['updatedRange'].split('!')[1].split(':')[0][1:]


def update_data_in_sheet(service, values, row_number):
    """
    This function updates a row of data in the Google Sheets spreadsheet.

    It first creates a body with the data, then calls the Google Sheets API to update the data in the spreadsheet.
    It returns the result of the update operation.
    """
    body = {'values': [values]}
    result = service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range=f"{RANGE_NAME.split('!')[0]}!A{row_number}",
        valueInputOption='USER_ENTERED', body=body).execute()
    return result


def generate_greeting():
    """
    This function generates a greeting based on the current time.

    It checks the current hour and returns a greeting appropriate for the time of day.
    """
    current_hour = datetime.now().hour
    if 5 <= current_hour < 12:
        return "Good morning! Please enter the password to use this bot."
    elif 12 <= current_hour < 17:
        return "Good afternoon! Please enter the password to use this bot."
    else:
        return "Good evening! Please enter the password to use this bot."


@bot.message_handler(commands=['start'])
def send_welcome(message):
    """
    This function sends a welcome message to the user when they start the bot.

    It generates a greeting and sends it to the user.
    """
    greeting = generate_greeting()
    bot.send_message(message.chat.id, greeting)


@bot.message_handler(func=lambda message: message.text.lower() == PASSWORD.lower())
def password_check(message):
    """
    This function checks the password entered by the user.

    If the password is correct, it sets the user's status to 'authenticated' and sends them the category buttons.
    """
    user_states[message.chat.id] = {'status': 'authenticated'}
    send_category_buttons(message)


def send_category_buttons(message):
    """
    This function sends the category buttons to the user.

    It creates a markup with the categories and sends it to the user.
    """
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, row_width=1)
    categories = ['Food', 'Travel', 'Groceries', 'Car Expenses',
                  'Repairs & Maintenance', 'Office Supplies', 'Business Tools',
                  'Ad & Promo', 'Telecom', 'Continuing Education', 'Other']
    for category in categories:
        markup.add(category)
    msg = bot.reply_to(message, "Choose the category of your receipt:", reply_markup=markup)
    bot.register_next_step_handler(msg, receive_category)


def receive_category(message):
    """
    This function receives the category selected by the user.

    It sets the category and the user's status, then asks the user to send a photo of their receipt.
    """
    global category
    category = message.text
    user_states[message.chat.id] = {'category': category, 'status': 'waiting_for_receipt'}
    bot.reply_to(message, f"Category '{category}' selected. Please send me the photo of your receipt.")


@bot.message_handler(content_types=['photo'])
def handle_docs_photo(message):
    """
    This function handles a photo sent by the user.

    If the user's status is 'waiting_for_receipt', it processes the photo and presents the extracted data to the user.
    If the user's status is not 'waiting_for_receipt', it asks the user to select a category first.
    """
    if user_states[message.chat.id]['status'] == 'waiting_for_receipt':
        try:
            chat_id = message.chat.id
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            base64_image = base64.b64encode(downloaded_file).decode('utf-8')
            extracted_data = process_receipt_with_openai(base64_image)
            parse_receipt_data(extracted_data, chat_id)
            present_receipt_data(chat_id)
        except Exception as e:
            print("Error handling photo: ", str(e))
            bot.reply_to(message, "Failed to process the image.")
    else:
        bot.reply_to(message, "Please select a category first.")


def present_receipt_data(chat_id, is_correction=False):
    """
    This function presents the extracted data to the user.

    It formats the data and sends it to the user. If the data is not being corrected, it also appends the data to the
    Google Sheets spreadsheet and stores the row number. Then it asks the user if there are any errors in the data.
    """
    global store_name, total_price, gst, hst, pst, date
    receipt = user_states[chat_id]['receipt']
    extracted_info = "\n".join([f"{key}: {value}" for key, value in receipt.items()])
    print(f"Extracted Info:\nCategory: {category}\n{extracted_info}")  # Print formatted info
    bot.send_message(chat_id, f"Category: {category}\n" + extracted_info)
    if not is_correction:
        service = authenticate_google_api()
        values = [category, store_name, total_price, gst, hst, pst, date]
        row_number = append_data_to_sheet(service, values)
        user_states[chat_id]['row_number'] = row_number  # Store the row number
    ask_for_correction(chat_id)


def ask_for_correction(chat_id):
    """
    This function asks the user if there are any errors in the data.

    It sends a message to the user asking if there are any errors, with 'Yes' and 'No' buttons.
    """
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True)
    markup.add('Yes', 'No')
    msg = bot.send_message(chat_id, "Are there any errors in the data?", reply_markup=markup)
    bot.register_next_step_handler(msg, error_check)


def error_check(message):
    """
    This function checks if there are any errors in the data.

    If the user selects 'Yes', it asks the user which part has an error.
    If the user selects 'No', it sends a message to the user saying that the receipt processing is complete.
    If the user selects neither 'Yes' nor 'No', it asks the user to choose 'Yes' or 'No'.
    """
    chat_id = message.chat.id
    if message.text == 'Yes':
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True)
        markup.add('Store Name', 'Total Price', 'GST', 'HST', 'PST', 'Date')
        msg = bot.send_message(chat_id, "Which part has an error?", reply_markup=markup)
        bot.register_next_step_handler(msg, part_selection)
    elif message.text == 'No':
        bot.send_message(chat_id, "Thank you. The receipt processing is complete.")
    else:
        bot.send_message(chat_id, "Please choose 'Yes' or 'No'.")


def part_selection(message):
    """
    This function receives the part selected by the user to correct.

    It stores the part to correct and asks the user to enter the correct value.
    """
    chat_id = message.chat.id
    part_to_correct = message.text
    user_states[chat_id]['correction'] = part_to_correct
    msg = bot.reply_to(message, f"Please enter the correct {part_to_correct}:")
    bot.register_next_step_handler(msg, correct_data)


def correct_data(message):
    """
    This function corrects a part of the receipt data.

    It first gets the part to correct and the corrected value from the user's message.
    It then updates the receipt data and the global variables with the corrected value.
    It authenticates the Google API, gets the row number where the data was written, and clears the original row.
    It then updates the row with the corrected data and presents the corrected data to the user.
    """
    chat_id = message.chat.id
    part_to_correct = user_states[chat_id]['correction']
    user_states[chat_id]['receipt'][part_to_correct] = message.text
    # Update the global variables
    global store_name, total_price, gst, hst, pst, date
    store_name = user_states[chat_id]['receipt'].get('Store Name', store_name)
    total_price = user_states[chat_id]['receipt'].get('Total Price', total_price)
    gst = user_states[chat_id]['receipt'].get('GST', gst)
    hst = user_states[chat_id]['receipt'].get('HST', hst)
    pst = user_states[chat_id]['receipt'].get('PST', pst)
    date = user_states[chat_id]['receipt'].get('Date', date)
    service = authenticate_google_api()
    row_number = user_states[chat_id]['row_number']  # Get the row number
    # Clear the original row
    service.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{RANGE_NAME.split('!')[0]}!A{row_number}:G{row_number}",
        body={}
    ).execute()
    # Update the row with the corrected data
    values = [category, store_name, total_price, gst, hst, pst, date]
    update_data_in_sheet(service, values, row_number)
    present_receipt_data(chat_id, is_correction=True)


def parse_receipt_data(assistant_message, chat_id):
    """
    This function parses the receipt data returned by the OpenAI API.

    It splits the data into lines, then splits each line into a key and a value.
    It stores the key-value pairs in a dictionary and updates the global variables with the values.
    """
    global store_name, total_price, gst, hst, pst, date
    lines = assistant_message.split('\n')
    receipt_dict = {}
    for line in lines:
        parts = line.split(':')
        if len(parts) == 2:
            key, value = parts[0].strip(), parts[1].strip()
            receipt_dict[key] = value
            if key == "Store Name":
                store_name = value
            elif key == "Total Price":
                total_price = value
            elif key == "GST":
                gst = value if value.strip() else "$0.00"
            elif key == "HST":
                hst = value if value.strip() else "$0.00"
            elif key == "PST":
                pst = value if value.strip() else "$0.00"
            elif key == "Date":
                date = value
    user_states[chat_id]['receipt'] = receipt_dict


def process_receipt_with_openai(base64_image):
    """
    This function processes a receipt image with the OpenAI API.

    It first sets up the headers and payload for the API request, including the base64-encoded image.
    It then sends a POST request to the API and gets the response.
    If the response contains choices, it gets the assistant's message from the first choice.
    If the response does not contain choices, it sets the assistant's message to an error message.
    It then returns the assistant's message.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    payload = {
        "model": "gpt-4-turbo",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Fill the blanks, Store Name: , Total Price: , GST:, HST:, PST: , and Date: from this image."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 300
    }
    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    response_json = response.json()

    if 'choices' in response_json and response_json['choices']:
        assistant_message = response_json['choices'][0]['message']['content']
    else:
        assistant_message = "Failed to get a valid response from OpenAI API."

    return assistant_message


if __name__ == '__main__':
    bot.polling(none_stop=True)
