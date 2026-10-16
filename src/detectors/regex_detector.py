import re

# Convert Arabic-Indic and Persian digits to ASCII digits.
DIGIT_MAP = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789"
)
# Dictionary of regex patterns so we can easily add more patterns in the future. The keys are the labels for the detected entities, and the values are the compiled regex patterns.
PATTERNS  = {
    "private_email": re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])"),# use compile to convert the pattern to a regex object that is ready to be ** reused for matching **
    "private_phone": re.compile(r"(?<![\w+])(?:\+966|00966|0)5(?:[\s-]?[0-9]){8}(?!\w)"),
    "national_id": re.compile(r"(?<!\w)1[0-9]{9}(?!\w)"),
    "iqama": re.compile( r"(?<!\w)2[0-9]{9}(?!\w)"),
}
# 
def detect_entities(text: str) -> list[dict]:
    normalized = text.translate(DIGIT_MAP)
    matches = [] # before deleting overlaps
# the loop go throgh each label and pattern in the PATTERNS dictionary, and for each pattern, it finds all matches in the normalized text. For each match, it creates a dictionary with the label, start and end positions, and the matched text, and appends it to the matches list.
    for label, pattern in PATTERNS.items(): # items method returns an ordered pairs of kay and value from pattrens 
        for match in pattern.finditer(normalized): # after choosing one pattern we apply it on the normalized text and return an iterator contains match object
                start = match.start()
                end = match.end()

                matches.append({
                    "label": label,
                    "start": start,
                    "end": end,
                    "text": text[start:end] # original text
                })
    # Prioritize earlier and longer matches
    matches.sort( # we use key for sorting cause we have dict to select the sorting strategy 
         key=lambda item: (
              item["start"], # the sort is based on entities at the beginning of the message 
              -(item["end"] - item["start"]) # and then longger messages apears first
         )
    ) 
    # Avoid returning overlapping detections
    results = [] # accepted results 

    for item in matches:
         overlaps = any( # returns true if at least one item is true
              item["start"] < old["end"]
              and old["start"] < item["end"]
              for old in results # compares the current entity with every old one has been accepted 
         )   

         if not overlaps:
                results.append(item)

    return results
# It classify the texts based on detect_entities results
def classify_message(text:str) -> str:
      entities = detect_entities(text)
      return "BLOCK" if entities else "ALLOW" # if entities empty = False, if not = True

    









