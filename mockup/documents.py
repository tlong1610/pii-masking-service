"""Dựng document giả. battery_contracts và battery_bills giữ đúng tên trường, độ lồng và kiểu BSON của bản mẫu."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from bson.decimal128 import Decimal128
from bson.int64 import Int64

from mockup.values import FakeValues

_MIN_DATE = datetime(1, 1, 1, tzinfo=UTC)
_MODELS = ["DEMO E1", "DEMO E2 - PLUS", "DEMO E3 - ORIGINAL"]


def _audit(v: FakeValues, created_by: str) -> dict:
    created = v.date()
    return {
        "_id": v.object_id(),
        "CreatedDate": created,
        "CreatedBy": created_by,
        "ModifiedDate": created + timedelta(hours=v.rng.randint(0, 2000)),
        "ModifiedBy": created_by,
        "DeletedDate": None,
        "DeletedBy": None,
        "IsDeleted": v.rng.random() < 0.1,
    }


def _creator(v: FakeValues) -> str:
    """Trường người tạo lẫn mã hệ thống và email người thật."""
    return "Integration" if v.rng.random() < 0.5 else v.staff_email()


def _money(amount: int) -> Decimal128:
    return Decimal128(Decimal(amount))


def make_customer(v: FakeValues, index: int) -> dict:
    enterprise = v.rng.random() < 0.15
    name = v.full_name()
    return {
        "_id": v.object_id(),
        "CustomerId": f"2008{index:08d}",
        "SapCustomerId": v.digits(10),
        "FullName": name,
        "Email": v.email(name),
        "PhoneNumber": v.phone(),
        "IdNumber": v.cccd(),
        "DateOfBirth": v.birth_date(),
        "Address": v.address(),
        "EnterpriseCustomer": enterprise,
        "TaxRegistrationNumber": v.company_tax_code() if enterprise else v.personal_tax_code(),
        "TaxRegistrationName": v.company_name() if enterprise else name,
        # Tên cột mơ hồ: c1, c2 chứa PII, c3 là mã nội bộ 12 số trông giống CCCD.
        "c1": v.cccd(),
        "c2": v.phone(),
        "c3": v.digits(12),
    }


def make_contract(v: FakeValues, customer: dict) -> dict:
    vin = v.vin()
    signed = v.date()
    return {
        **_audit(v, _creator(v)),
        "MultilingualData": None,
        "ActiveDate": signed,
        "ContractNo": f"10A3-DM{v.rng.randint(1, 9)}-{v.digits(8)}",
        "CreatedShowroom": v.rng.choice(["10A3", "10B1", "20C2"]),
        "FullName": customer["FullName"],
        "Email": customer["Email"],
        "PhoneNumber": customer["PhoneNumber"],
        "IdNumber": customer["IdNumber"],
        "Address": customer["Address"],
        "CustomerId": customer["CustomerId"],
        "SapCustomerId": customer["SapCustomerId"],
        "VehicleId": vin,
        "VehicleType": "Car",
        "VehicleModel": v.rng.choice(_MODELS),
        "Batteries": [
            {
                "_id": None,
                "CreatedDate": _MIN_DATE,
                "CreatedBy": None,
                "ModifiedDate": None,
                "ModifiedBy": None,
                "DeletedDate": None,
                "DeletedBy": None,
                "IsDeleted": False,
                "Serial": vin,
                "Stock": vin,
                "Capacity": "500",
                "Type": "0",
                "Status": "1",
                "Enabled": True,
                "BatteryProblems": [],
            }
        ],
        "Status": v.rng.randint(0, 3),
        "BatteryDeposit": "0",
        "TaxRegistrationNumber": customer["TaxRegistrationNumber"],
        "TaxRegistrationName": customer["TaxRegistrationName"],
        "EnterpriseCustomer": customer["EnterpriseCustomer"],
        "FromSource": 1,
        "LiquidationDate": None,
        "PackageType": v.rng.randint(0, 2),
        "BatteryPackageId": str(v.object_id()),
        "UploadedToOneProfile": None,
        "IsSubContract": v.rng.random() < 0.5,
        "SubContractSignDate": signed,
        "IsInfoValid": True,
        "IsFree": False,
        "IsBatteryOwner": False,
        "Promotion": f"PROMO_{v.digits(4)}",
        "CancelationDate": None,
        "DownPaymentDate": signed,
        "InvoiceDate": signed,
        "Flag": 0,
    }


def _paid_at(v: FakeValues, method: int) -> dict:
    return {
        "StoreCode": v.rng.choice(["10A3", "10B1", "20C2"]),
        "StoreName": f"Showroom Demo {v.digits(2)}",
        "StoreType": "6",
        "StoreDistrict": "MB.Vùng 2",
        "StoreCity": "Hà Nội",
        # Địa chỉ cửa hàng không phải địa chỉ cá nhân.
        "StoreAddress": v.address() if v.rng.random() < 0.5 else None,
        "PaymentMethod": method,
        "TransactionId": v.digits(12) if v.rng.random() < 0.5 else None,
        "BankName": "Ngân hàng Demo",
        "AccountNumber": v.bank_account(),
        # Tài khoản kế toán nội bộ, không phải tài khoản của người dùng.
        "AccountCashInBank": v.digits(10),
        "AccountCashInTransit": v.digits(10),
        "VoucherCode": None,
        "VoucherAmount": None,
    }


def _leasing_data(v: FakeValues, contract_no: str, cost: int) -> dict:
    start = v.date()
    return {
        "PackageName": None,
        "PackageId": str(v.object_id()),
        "ContractNo": contract_no,
        "InitialOdo": 0.0,
        "EndOdo": 2000.0,
        "LimitKm": 500.0,
        "ActualKm": 2000.0,
        "OverKm": 1500.0,
        "Price": "1315",
        "Cost": str(cost),
        "FromDate": start,
        "ToDate": start + timedelta(days=30),
        "LastUpdate": start + timedelta(days=30),
        "PackageType": 0,
        "OverAmount": None,
        "NumberOfAppliedDays": "0",
        "NumberOfRemainingDays": "0",
        "PackageLeasingData": None,
        "ExceedAmount": None,
        "ExceedCycle": None,
        "IsExceed": False,
        "GroupType": None,
        "ExceedData": None,
        "PackageProperty": None,
        "PackageCostPolicy": None,
        "GroupPolicyCode": None,
        "AllPackageCostPolicy": None,
        "MinCost": "0",
        "TransportationStatusCode": None,
    }


def make_bill(v: FakeValues, customer: dict, contract: dict) -> dict:
    audit = _audit(v, _creator(v))
    issued = audit["CreatedDate"]
    method = v.rng.randint(1, 3)
    card = v.card_number() if v.rng.random() < 0.3 else None
    amount = v.rng.randrange(500_000, 6_000_000, 1000)
    final_amount = amount - v.rng.randrange(0, 400_000, 1000)
    has_tax_code = customer["EnterpriseCustomer"] or v.rng.random() < 0.2
    return {
        **audit,
        "MultilingualData": {},
        "BillCode": None,
        "CustomerId": customer["CustomerId"],
        "SapCustomerId": customer["SapCustomerId"],
        "VehicleId": contract["VehicleId"],
        "VehicleModel": contract["VehicleModel"],
        "FullName": customer["FullName"],
        "Email": customer["Email"],
        "PhoneNumber": customer["PhoneNumber"],
        "IDNumber": customer["IdNumber"],
        "Address": customer["Address"],
        "ServiceType": "EMSP_PAYMENT",
        "Type": 1,
        "SubType": v.rng.randint(1, 3),
        "IssuedDate": issued,
        "PaymentMethod": method,
        "PaymentMethodHistory": [method],
        "PaidDate": issued + timedelta(minutes=v.rng.randint(1, 500)),
        "PaymentTranId": None,
        "Amount": _money(amount),
        "BillStatus": v.rng.randint(0, 2),
        "Paid": True,
        "InvoiceStatus": 0,
        "InvoiceInfo": None,
        "BillParrentId": None,
        "IsAdjustment": False,
        "IsHolding": None,
        "ChargingSubscriptionVehicleId": None,
        "SapDocument": None,
        "Discount": _money(0),
        "VoucherDiscountAmount": None,
        "FinalAmount": _money(final_amount),
        "SapBusinessPlace": "0000",
        "ProfitCenter": v.digits(8),
        "VendorCode": None,
        "IsInvoice": False,
        "VatRate": _money(8),
        "VatAmount": _money(final_amount * 8 // 108),
        "ContractNo": contract["ContractNo"],
        "LockTime": None,
        "LockBySource": None,
        "BinCode": card[:6] if card else None,
        "CardNumber": card,
        "ChargingBookingCode": None,
        "BatterySerial": contract["Batteries"][0]["Serial"],
        "RegisteredInvoice": False,
        "EnterpriseCustomer": customer["EnterpriseCustomer"],
        "PaidAt": _paid_at(v, method),
        "IsUploadToSap": True,
        "Promotions": [],
        "DueDate": issued + timedelta(days=1),
        "CampaignIds": None,
        "LeasingData": _leasing_data(v, contract["ContractNo"], final_amount),
        "BookingData": None,
        "ChangeRequestData": None,
        "BatteryProblemData": None,
        "PaymentArrearsInfo": None,
        "LeasingFeeCutOffData": {"TotalAmountCutOff": "0", "TotalDaysCutOff": "0", "Request": None},
        "LeasingPromotionOrderDataInfo": None,
        "SecureHash": v.hex_upper(64),
        "TaxRegistrationNumber": customer["TaxRegistrationNumber"] if has_tax_code else "",
        "RedeemSessionId": None,
    }


def _spaced_phone(phone: str) -> str:
    return f"{phone[:4]} {phone[4:7]} {phone[7:]}"


def _build_text(parts: list) -> tuple[str, list[dict]]:
    """parts gồm chuỗi thường và cặp (loại PII, giá trị); trả văn bản và vị trí từng thực thể."""
    text, spans = "", []
    for part in parts:
        if isinstance(part, tuple):
            pii_type, value = part
            spans.append({"type": pii_type, "start": len(text), "end": len(text) + len(value)})
            text += value
        else:
            text += part
    return text, spans


def make_ticket(v: FakeValues, customer: dict, index: int) -> tuple[dict, list[dict]]:
    name = ("FULL_NAME", customer["FullName"])
    phone = ("PHONE", customer["PhoneNumber"])
    spaced_phone = ("PHONE", _spaced_phone(customer["PhoneNumber"]))
    email = ("EMAIL", customer["Email"])
    cccd = ("CCCD", customer["IdNumber"])
    address = ("ADDRESS", customer["Address"])
    account = ("BANK_ACCOUNT", v.bank_account())
    card = ("CREDIT_CARD", v.card_number())
    birth_date = ("DOB", customer["DateOfBirth"].strftime("%d/%m/%Y"))
    # Mã số thuế doanh nghiệp trong câu không phải PII nên không có nhãn.
    tax_code = customer["TaxRegistrationNumber"]
    tax_code = tax_code if customer["EnterpriseCustomer"] else ("TAX_CODE", tax_code)
    waybill = v.digits(12)
    templates = [
        ["Khách ", name, " gọi từ số ", phone, " báo pin sạc chậm, cần kiểm tra."],
        ["Anh ", name, " ở ", address, " yêu cầu đổi lịch bảo dưỡng."],
        ["Liên hệ ", spaced_phone, " để xác nhận, mã vận đơn ", waybill, " đã giao."],
        ["Xác minh CCCD ", cccd, " của ", name, " trước khi cấp lại hợp đồng."],
        ["Gửi hóa đơn về ", email, ", hoàn tiền vào tài khoản ", account, "."],
        ["Pin lỗi cảm biến nhiệt, mã vận đơn ", waybill, ", chưa cần liên hệ khách."],
        ["Khách sinh ngày ", birth_date, ", cần cập nhật lại hồ sơ."],
        ["Xuất hóa đơn theo mã số thuế ", tax_code, " cho hợp đồng mới."],
        ["Hoàn tiền vào thẻ ", card, " trong 3 ngày làm việc."],
    ]
    note, spans = _build_text(v.rng.choice(templates))
    doc = {
        "_id": v.object_id(),
        "TicketNo": f"TK-{index:06d}",
        "CustomerId": customer["CustomerId"],
        "Subject": v.rng.choice(["Pin sạc chậm", "Đổi lịch bảo dưỡng", "Yêu cầu hoàn tiền", "Cấp lại hợp đồng"]),
        "Note": note,
        "AssignedTo": v.staff_email(),
        "Status": v.rng.randint(0, 3),
        "CreatedDate": v.date(),
    }
    return doc, spans


def make_device(v: FakeValues, index: int) -> dict:
    """Toàn mã nghiệp vụ dùng làm hard negative để đo precision."""
    return {
        "_id": v.object_id(),
        "DeviceCode": f"DEV-{index:06d}",
        "Serial": f"V{v.digits(17)}",
        "Imei": v.digits(15),
        "WaybillNo": v.digits(12),
        "ContractNo": f"N{v.digits(5)}-25-{v.digits(4)}",
        "Weight": Int64(v.rng.randint(200, 500)),
    }
