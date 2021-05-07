import time
import telegram_send
import requests
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, ConversationHandler
import logging
import re

class CovidVaccineBot:
    def __init__(self, token, debug = False):
        self.token = token
        self.clients = {}
        
        # Enable bot logging
        logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level = logging.DEBUG if debug else logging.WARN)
        botLogger = logging.getLogger(__name__)

    def startBot(self):
        self.updater = Updater(self.token)
        # Get the dispatcher to register handlers
        dispatcher = self.updater.dispatcher

        self.COMMANDS_SUPPORTED = [
            "start",
            "stop",
            "checkNow",
            "help"
        ]
        # on different commands - answer in Telegram
        dispatcher.add_handler(CommandHandler("help", self.commandHelp))
        dispatcher.add_handler(ConversationHandler(
            entry_points=[CommandHandler('start', self.commandStart)],
            states={
                0: [MessageHandler(Filters.text, self.registerForTracking)],
            },
            fallbacks=[CommandHandler('cancel', self.commandCancelConversation)],
        ))
        dispatcher.add_handler(CommandHandler("stop", self.commandStop))
        dispatcher.add_handler(CommandHandler("checkNow", self.commandCheckNow))
        dispatcher.add_handler(CommandHandler("allClients", self.commandAllClients))

        # Start the Bot
        self.updater.start_polling()
        self.updater.idle()
    
    def commandHelp(self, update: Update, context: CallbackContext) -> None:
        helpMessage = "You can use any of the following commands:\n"
        for command in self.COMMANDS_SUPPORTED:
            helpMessage += "\n/" + command
        update.message.reply_text(helpMessage)

    def commandStart(self, update: Update, context: CallbackContext) -> int:
        update.message.reply_text('Enter pincodes (comma separated)')
        return 0
    
    def registerForTracking(self, update: Update, context: CallbackContext) -> int:
        try:
            pincodesText = update.message.text
            if re.search('^\d{6}(,\d{6})*$', pincodesText):
                pincodes = pincodesText.split(",")
                if update.message.chat.id in self.clients and self.clients[update.message.chat.id] is not None:
                    try:
                        self.clients[update.message.chat.id]["scheduler"].shutdown()
                    except Exception as e:
                        print("Error in shuting down: ", e)
                self.clients[update.message.chat.id] = {
                    "pincodes": pincodes,
                    "scheduler": BackgroundScheduler(),
                    "name": update.message.chat.first_name + " " + update.message.chat.last_name
                }
                self.clients[update.message.chat.id]["scheduler"].add_job(self.searchForVaccineCentres, 'interval', seconds = 300, args = [pincodes, update.message.chat.id])
                self.clients[update.message.chat.id]["scheduler"].start()
                self.searchForVaccineCentres(pincodes, update.message.chat.id, silentSearch = False)

                helpMessage = "\n\nYou can use any of the following commands:\n"
                for command in self.COMMANDS_SUPPORTED:
                    helpMessage += "\n/" + command
                update.message.reply_text("Vaccine Tracker Registration Successful" + helpMessage)
            else:
                update.message.reply_text("Invalid Pincodes. Registration Cancelled.\nSend /start to retry.")
        except Exception as e:
            update.message.reply_text("Vaccine Tracker Registration Failed")

        return ConversationHandler.END

    def searchForVaccineCentres(self, pincodes, chatId, silentSearch = True):
        try:
            if not silentSearch:
                self.updater.bot.sendMessage(chatId, "Searching for vaccine...")
            centres = []
            currentDate = datetime.datetime.now().strftime("%d-%m-%Y")
            for pincode in pincodes:
                url = "https://cdn-api.co-vin.in/api/v2/appointment/sessions/public/calendarByPin?pincode=" + pincode + "&date=" + currentDate
                response = requests.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0"
                })
                if response.status_code == 200:
                    data = response.json()
                    centres += data['centers']
                else:
                    self.updater.bot.sendMessage(chatId, "API Returned status {} for Pincode {}".format(response.status_code, pincode))
            found = False
            for centre in centres:
                sessions = centre['sessions']
                sessionDetails = ""
                for session in sessions:
                    if session['available_capacity'] > 0:
                        found = True
                        sessionDetails += "\n\n{}\nAge: {}+\nAvailable: {}\nVaccine: {}\nSlots:\n{}".format(session["date"], session["min_age_limit"], session["available_capacity"], session["vaccine"], session["slots"])
                if sessionDetails != "":
                    self.updater.bot.sendMessage(chatId, "{}\n{}\n{}\n\n{} to {}\nFees: {}{}".format(centre["name"], centre["address"], centre["pincode"], centre["from"], centre["to"], centre["fee_type"], sessionDetails))           
                    
            if not found and not silentSearch:
                self.updater.bot.sendMessage(chatId, "Couldn't find any session")
        except Exception as e:
            if not silentSearch:
                try:
                    self.updater.bot.sendMessage(chatId, "Error Occured: " + str(e))
                except Exception as e:
                    print("Error Occured: " + str(e))

    def commandStop(self, update: Update, context: CallbackContext) -> None:
        try:
            if update.message.chat.id in self.clients and self.clients[update.message.chat.id] is not None:
                self.clients[update.message.chat.id]["scheduler"].shutdown()
                self.clients[update.message.chat.id] = None
            update.message.reply_text("Vaccine Tracker Stopped")
        except Exception as e:
            update.message.reply_text("Stopping Vaccine Tracker Failed")

    def commandCancelConversation(self, update: Update, context: CallbackContext) -> int:
        update.message.reply_text('Registration Cancelled.\nSend /start to retry.')
        return ConversationHandler.END
    
    def commandCheckNow(self, update: Update, context: CallbackContext) -> None:
        try:
            if update.message.chat.id in self.clients and self.clients[update.message.chat.id] is not None:
                update.message.reply_text("Vaccine Tracker is running for following pincodes:\n" + str(self.clients[update.message.chat.id]["pincodes"]))
                self.searchForVaccineCentres(self.clients[update.message.chat.id]["pincodes"], update.message.chat.id, silentSearch = False)
            else:
                update.message.reply_text("Vaccine Tracker not registered.\nSend /start to register.")
        except Exception as e:
            update.message.reply_text("Vaccine Tracker Registration Failed")

    def commandAllClients(self, update: Update, context: CallbackContext) -> None:
        try:
            message = "Following users are registered:"
            for chatId in self.clients:
                if self.clients[chatId] is not None:
                    message += "\n\nChat ID: {}\nName: {}\nPincodes: {}".format(chatId, self.clients[chatId]["name"], self.clients[chatId]["pincodes"])
            update.message.reply_text(message)
        except Exception as e:
            update.message.reply_text("Error sending registered clients")

try:
    TOKEN = "<ENTER YOUR TELEGRAM BOT TOKEN HERE>"
    covidVaccineBot = CovidVaccineBot(TOKEN, False)
    covidVaccineBot.startBot()
except Exception as e:
    print(e)
    time.sleep(60)

