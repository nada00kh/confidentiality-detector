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
# with the highest priority. The frozen detector (model + rules v3) is the evaluated core
# system, so its label is kept. The Saudi rules are a demo-only extension: they add values
# the core detector missed, but never replace the type of a core finding (for example the
# IBAN DE89 3704 0044 0532 0130 00 stays IBAN, although "0532 0130 00" matches the Saudi phone rule).
LABEL_PRIORITY = {label: 1 for label in MODEL_LABEL_TO_CODE}  # Saudi labels: 0

# Secondary explanations (demo only). When a Saudi rule matches a value that the core detector
# typed differently (for example a national ID typed ACCOUNTNUMBER), the response keeps the core
# type and adds one of these hints in a separate field. A hint is a format match only: it does not
# show that the value is a real or verified ID, and it is never stored or counted.
SAUDI_PATTERN_HINTS = {
    "national_id": ("SAUDI_NATIONAL_ID", "Also matches a Saudi national ID pattern (demo rule)."),
    "iqama": ("SAUDI_IQAMA", "Also matches an Iqama-like pattern (demo rule)."),
    "private_phone": ("SAUDI_MOBILE", "Also matches a Saudi mobile number pattern (demo rule)."),
}
