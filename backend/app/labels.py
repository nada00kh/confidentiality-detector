"""Data type codes shown by the frontend, and how detector labels map onto them.

A label that is not listed in LABEL_TO_CODE is treated as a masking failure, so an
unexpected detector output can never slip through unmasked.
"""

TYPE_LABELS = {
    # Codes from the frontend contract (API_CONTRACT.md).
    "PERSON_NAME": "Person name",
    "NATIONAL_ID": "National ID",
    "PHONE": "Phone number",
    "EMAIL": "Email address",
    "IBAN": "IBAN",
    "CARD_NUMBER": "Card number",
    "PASSWORD": "Password",
    "CONFIDENTIAL": "Confidential topic",
    # Additional codes for detector labels with no matching contract code.
    "IQAMA": "Iqama number",
    "SSN": "Social Security number",
    "CARD_CVV": "Card security code",
    "USERNAME": "Username",
    "ACCOUNT_NUMBER": "Account number",
    "STREET_ADDRESS": "Street address",
    "IP_ADDRESS": "IP address",
}

# Labels of the Saudi rules (saudi_rules.py).
SAUDI_LABEL_TO_CODE = {
    "private_email": "EMAIL",
    "private_phone": "PHONE",
    "national_id": "NATIONAL_ID",
    "iqama": "IQAMA",
}

# The 13 entity labels of the frozen detector (confidentiality_detector.labels.TARGET_LABELS).
# The model predicts BIO tags (B-FIRSTNAME, I-FIRSTNAME, ...); the frozen package decodes
# them into spans carrying these plain labels.
MODEL_LABEL_TO_CODE = {
    "FIRSTNAME": "PERSON_NAME",
    "LASTNAME": "PERSON_NAME",
    "SSN": "SSN",
    "PHONENUMBER": "PHONE",
    "EMAIL": "EMAIL",
    "IBAN": "IBAN",
    "CREDITCARDNUMBER": "CARD_NUMBER",
    "CREDITCARDCVV": "CARD_CVV",
    "PASSWORD": "PASSWORD",
    "USERNAME": "USERNAME",
    "ACCOUNTNUMBER": "ACCOUNT_NUMBER",
    "STREET": "STREET_ADDRESS",
    "IPV4": "IP_ADDRESS",
}

LABEL_TO_CODE = {**SAUDI_LABEL_TO_CODE, **MODEL_LABEL_TO_CODE}

# When spans overlap, the masked span covers all of them and takes the type of the label
# with the highest priority. The Saudi rules match exact Saudi formats, so they win over the
# English-trained model, which labels Saudi IDs and phone numbers as ACCOUNTNUMBER.
LABEL_PRIORITY = {label: 1 for label in SAUDI_LABEL_TO_CODE}  # model labels: 0
