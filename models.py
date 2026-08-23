"""
ORM models untuk database 'payment' (PostgreSQL).
Mencerminkan skema di schema.sql — 8 tabel.
"""

from sqlalchemy import (
    Column, Integer, String, Numeric, TIMESTAMP, ForeignKey,
    Boolean, Float, LargeBinary, CheckConstraint, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db import Base


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    phone_number = Column(String(20), unique=True, nullable=False)
    pin_hash = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    account = relationship("Account", back_populates="user", uselist=False)
    biometrics = relationship("PalmBiometric", back_populates="user")
    scan_logs = relationship("ScanLog", back_populates="user")


class PalmBiometric(Base):
    __tablename__ = "palm_biometrics"

    biometric_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    hand_side = Column(String(10), nullable=False)
    embedding_avg = Column(LargeBinary, nullable=False)
    enrolled_at = Column(TIMESTAMP, server_default=func.now())
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("hand_side IN ('left', 'right')", name="chk_hand_side"),
    )

    user = relationship("User", back_populates="biometrics")
    frames = relationship("BiometricFrame", back_populates="biometric", cascade="all, delete-orphan")


class BiometricFrame(Base):
    __tablename__ = "biometric_frames"

    frame_id = Column(Integer, primary_key=True)
    biometric_id = Column(Integer, ForeignKey("palm_biometrics.biometric_id", ondelete="CASCADE"), nullable=False)
    embedding_raw = Column(LargeBinary, nullable=False)
    quality_score = Column(Float)
    captured_at = Column(TIMESTAMP, server_default=func.now())

    biometric = relationship("PalmBiometric", back_populates="frames")


class Account(Base):
    __tablename__ = "accounts"

    account_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), unique=True)
    account_number = Column(String(20), unique=True, nullable=False)
    balance = Column(Numeric(15, 2), nullable=False, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        CheckConstraint("balance >= 0", name="chk_balance_non_negative"),
    )

    user = relationship("User", back_populates="account")
    outgoing_transactions = relationship(
        "Transaction", foreign_keys="Transaction.account_id", back_populates="account"
    )
    incoming_transactions = relationship(
        "Transaction", foreign_keys="Transaction.destination_account_id", back_populates="destination_account"
    )
    merchant = relationship("Merchant", back_populates="account", uselist=False)


class TransactionType(Base):
    __tablename__ = "transaction_types"

    type_id = Column(Integer, primary_key=True)
    type_name = Column(String(30), unique=True, nullable=False)

    transactions = relationship("Transaction", back_populates="type")


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.account_id"), nullable=False)
    destination_account_id = Column(Integer, ForeignKey("accounts.account_id"))
    type_id = Column(Integer, ForeignKey("transaction_types.type_id"), nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    balance_after = Column(Numeric(15, 2))  # snapshot saldo pasca-transaksi, untuk riwayat/audit trail
    reference_code = Column(String(40), unique=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_amount_positive"),
        CheckConstraint("status IN ('pending', 'success', 'failed')", name="chk_status_valid"),
    )

    account = relationship("Account", foreign_keys=[account_id], back_populates="outgoing_transactions")
    destination_account = relationship(
        "Account", foreign_keys=[destination_account_id], back_populates="incoming_transactions"
    )
    type = relationship("TransactionType", back_populates="transactions")
    scan_log = relationship("ScanLog", back_populates="transaction", uselist=False)


class Merchant(Base):
    __tablename__ = "merchants"

    merchant_id = Column(Integer, primary_key=True)
    merchant_name = Column(String(100), nullable=False)
    category = Column(String(50))
    account_id = Column(Integer, ForeignKey("accounts.account_id", ondelete="SET NULL"), unique=True)

    account = relationship("Account", back_populates="merchant")


class ScanLog(Base):
    __tablename__ = "scan_logs"

    log_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    transaction_id = Column(Integer, ForeignKey("transactions.transaction_id"))
    similarity_score = Column(Float, nullable=False)
    matched = Column(Boolean, nullable=False)
    scan_timestamp = Column(TIMESTAMP, server_default=func.now())

    user = relationship("User", back_populates="scan_logs")
    transaction = relationship("Transaction", back_populates="scan_log")
