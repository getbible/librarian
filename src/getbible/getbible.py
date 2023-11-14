import os
import json
import requests
import threading
import time
from datetime import datetime, timedelta
from getbible import GetBibleReference


class GetBible:
    def __init__(self, repo_path="https://api.getbible.net", version='v2'):
        """
        Initialize the GetBible class.

        Sets up the class by initializing the cache, starting the background thread for
        monthly cache reset, and other necessary setups.

        :param repo_path: The repository path, which can be a URL or a local file path.
        :param version: The version of the Bible repository.
        """
        self.__get = GetBibleReference()
        self.__repo_path = repo_path
        self.__repo_version = version
        self.__books_cache = {}
        self.__chapters_cache = {}
        self.__start_cache_reset_thread()
        # Determine if the repository path is a URL
        self.__repo_path_url = self.__repo_path.startswith("http://") or self.__repo_path.startswith("https://")

    def __start_cache_reset_thread(self):
        """
        Start a background thread to reset the cache monthly.

        This method creates and starts a daemon thread that runs the cache reset function
        every month.
        """
        reset_thread = threading.Thread(target=self.__reset_cache_monthly)
        reset_thread.daemon = True  # Daemonize thread
        reset_thread.start()

    def __reset_cache_monthly(self):
        """
        Periodically clears the cache on the first day of each month.

        This method runs in a background thread and calculates the time until the start
        of the next month. It sleeps until that time and then clears the cache.
        """
        while True:
            time_to_sleep = self.__calculate_time_until_next_month()
            time.sleep(time_to_sleep)
            self.__chapters_cache.clear()
            print(f"Cache cleared on {datetime.now()}")

    def __calculate_time_until_next_month(self):
        """
        Calculate the seconds until the start of the next month.

        Determines how many seconds are left until the first day of the next month
        from the current time. This duration is used by the cache reset thread to
        sleep until the cache needs to be cleared.

        :return: Number of seconds until the start of the next month.
        """
        now = datetime.now()
        # Calculate the first day of the next month
        first_of_next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
        return (first_of_next_month - now).total_seconds()

    def select(self, reference, abbreviation='kjv'):
        """
        Select and return Bible verses based on the reference and abbreviation.

        :param reference: The Bible reference (e.g., John 3:16).
        :param abbreviation: The abbreviation for the Bible translation.
        :return: dictionary of the selected Bible verses.
        """
        self.__check_translation(abbreviation)
        result = {}
        references = reference.split(';')
        for ref in references:
            try:
                reference = self.__get.ref(ref, abbreviation)
            except ValueError:
                raise ValueError(f"Invalid reference format.")

            self.__set_verse(abbreviation, reference.book, reference.chapter, reference.verses, result)

        return result

    def scripture(self, reference, abbreviation='kjv'):
        """
        Select and return Bible verses based on the reference and abbreviation.

        :param reference: The Bible reference (e.g., John 3:16).
        :param abbreviation: The abbreviation for the Bible translation.
        :return: JSON string of the selected Bible verses.
        """

        return json.dumps(self.select(reference, abbreviation))

    def __set_verse(self, abbreviation, book, chapter, verses, result):
        """
        Set verse information into the result JSON.
        :param abbreviation: Bible translation abbreviation.
        :param book: The book of the Bible.
        :param chapter: The chapter number.
        :param verses: List of verse numbers.
        :param result: The dictionary to store verse information.
        """
        cache_key = f"{abbreviation}_{book}_{chapter}"
        if cache_key not in self.__chapters_cache:
            chapter_data = self.__retrieve_chapter_data(abbreviation, book, chapter)
            # Convert verses list to dictionary for faster lookup
            verse_dict = {str(v["verse"]): v for v in chapter_data.get("verses", [])}
            chapter_data["verses"] = verse_dict
            self.__chapters_cache[cache_key] = chapter_data
        else:
            chapter_data = self.__chapters_cache[cache_key]

        for verse in verses:
            verse_info = chapter_data["verses"].get(str(verse))
            if not verse_info:
                raise ValueError(f"Verse {verse} not found in book {book}, chapter {chapter}.")

            if cache_key in result:
                existing_verses = {str(v["verse"]) for v in result[cache_key].get("verses", [])}
                if str(verse) not in existing_verses:
                    result[cache_key]["verses"].append(verse_info)
            else:
                # Include all other relevant elements of your JSON structure
                result[cache_key] = {key: chapter_data[key] for key in chapter_data if key != "verses"}
                result[cache_key]["verses"] = [verse_info]

    def __check_translation(self, abbreviation):
        """
        Check if the given translation is available.

        :param abbreviation: The abbreviation of the Bible translation to check.
        :raises FileNotFoundError: If the translation is not found.
        """
        path = self.__generate_path(abbreviation, "books.json")
        if abbreviation not in self.__books_cache:
            self.__books_cache[abbreviation] = self.__fetch_data(path)
            if self.__books_cache[abbreviation] is None:
                raise FileNotFoundError(f"Translation ({abbreviation}) not found in this API.")

    def __generate_path(self, abbreviation, file_name):
        """
        Generate the path or URL for a given file.

        :param abbreviation: Bible translation abbreviation.
        :param file_name: Name of the file to fetch.
        :return: Full path or URL to the file.
        """
        if self.__repo_path_url:
            return f"{self.__repo_path}/{self.__repo_version}/{abbreviation}/{file_name}"
        else:
            return os.path.join(self.__repo_path, self.__repo_version, abbreviation, file_name)

    def __fetch_data(self, path):
        """
        Fetch data from either a URL or a local file path.

        :param path: The path or URL to fetch data from.
        :return: The fetched data, or None if an error occurs.
        """
        if self.__repo_path_url:
            response = requests.get(path)
            if response.status_code == 200:
                return response.json()
            else:
                return None
        else:
            if os.path.isfile(path):
                with open(path, 'r') as file:
                    return json.load(file)
            else:
                return None

    def __retrieve_chapter_data(self, abbreviation, book, chapter):
        """
        Retrieve chapter data for a given book and chapter.

        :param abbreviation: Bible translation abbreviation.
        :param book: The book of the Bible.
        :param chapter: The chapter number.
        :return: Chapter data.
        :raises FileNotFoundError: If the chapter data is not found.
        """
        chapter_file = f"{str(book)}/{chapter}.json" if self.__repo_path_url else os.path.join(str(book),
                                                                                               f"{chapter}.json")
        chapter_data = self.__fetch_data(self.__generate_path(abbreviation, chapter_file))
        if chapter_data is None:
            raise FileNotFoundError(f"File {abbreviation}/{book}/{chapter}.json does not exist.")
        return chapter_data