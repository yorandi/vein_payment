--
-- PostgreSQL database dump
--

\restrict tEWfrVleu8STH4dMmChhTALghA9mfahRvYKchWxwzviM4fu1iUFxYHOm7frnYPT

-- Dumped from database version 15.18 (Raspbian 15.18-0+deb12u1)
-- Dumped by pg_dump version 15.18 (Raspbian 15.18-0+deb12u1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: admin
--

-- *not* creating schema, since initdb creates it


ALTER SCHEMA public OWNER TO admin;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: accounts; Type: TABLE; Schema: public; Owner: admin
--

CREATE TABLE public.accounts (
    account_id integer NOT NULL,
    user_id integer,
    account_number character varying(20) NOT NULL,
    balance numeric(15,2) DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT accounts_balance_check CHECK ((balance >= (0)::numeric))
);


ALTER TABLE public.accounts OWNER TO admin;

--
-- Name: accounts_account_id_seq; Type: SEQUENCE; Schema: public; Owner: admin
--

CREATE SEQUENCE public.accounts_account_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.accounts_account_id_seq OWNER TO admin;

--
-- Name: accounts_account_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: admin
--

ALTER SEQUENCE public.accounts_account_id_seq OWNED BY public.accounts.account_id;


--
-- Name: biometric_frames; Type: TABLE; Schema: public; Owner: admin
--

CREATE TABLE public.biometric_frames (
    frame_id integer NOT NULL,
    biometric_id integer NOT NULL,
    embedding_raw bytea NOT NULL,
    quality_score real,
    captured_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.biometric_frames OWNER TO admin;

--
-- Name: biometric_frames_frame_id_seq; Type: SEQUENCE; Schema: public; Owner: admin
--

CREATE SEQUENCE public.biometric_frames_frame_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.biometric_frames_frame_id_seq OWNER TO admin;

--
-- Name: biometric_frames_frame_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: admin
--

ALTER SEQUENCE public.biometric_frames_frame_id_seq OWNED BY public.biometric_frames.frame_id;


--
-- Name: merchants; Type: TABLE; Schema: public; Owner: admin
--

CREATE TABLE public.merchants (
    merchant_id integer NOT NULL,
    merchant_name character varying(100) NOT NULL,
    category character varying(50),
    account_id integer
);


ALTER TABLE public.merchants OWNER TO admin;

--
-- Name: merchants_merchant_id_seq; Type: SEQUENCE; Schema: public; Owner: admin
--

CREATE SEQUENCE public.merchants_merchant_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.merchants_merchant_id_seq OWNER TO admin;

--
-- Name: merchants_merchant_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: admin
--

ALTER SEQUENCE public.merchants_merchant_id_seq OWNED BY public.merchants.merchant_id;


--
-- Name: palm_biometrics; Type: TABLE; Schema: public; Owner: admin
--

CREATE TABLE public.palm_biometrics (
    biometric_id integer NOT NULL,
    user_id integer NOT NULL,
    hand_side character varying(10) NOT NULL,
    embedding_avg bytea NOT NULL,
    enrolled_at timestamp without time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    CONSTRAINT palm_biometrics_hand_side_check CHECK (((hand_side)::text = ANY ((ARRAY['left'::character varying, 'right'::character varying])::text[])))
);


ALTER TABLE public.palm_biometrics OWNER TO admin;

--
-- Name: palm_biometrics_biometric_id_seq; Type: SEQUENCE; Schema: public; Owner: admin
--

CREATE SEQUENCE public.palm_biometrics_biometric_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.palm_biometrics_biometric_id_seq OWNER TO admin;

--
-- Name: palm_biometrics_biometric_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: admin
--

ALTER SEQUENCE public.palm_biometrics_biometric_id_seq OWNED BY public.palm_biometrics.biometric_id;


--
-- Name: scan_logs; Type: TABLE; Schema: public; Owner: admin
--

CREATE TABLE public.scan_logs (
    log_id integer NOT NULL,
    user_id integer,
    transaction_id integer,
    similarity_score real NOT NULL,
    matched boolean NOT NULL,
    scan_timestamp timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.scan_logs OWNER TO admin;

--
-- Name: scan_logs_log_id_seq; Type: SEQUENCE; Schema: public; Owner: admin
--

CREATE SEQUENCE public.scan_logs_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.scan_logs_log_id_seq OWNER TO admin;

--
-- Name: scan_logs_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: admin
--

ALTER SEQUENCE public.scan_logs_log_id_seq OWNED BY public.scan_logs.log_id;


--
-- Name: transaction_types; Type: TABLE; Schema: public; Owner: admin
--

CREATE TABLE public.transaction_types (
    type_id integer NOT NULL,
    type_name character varying(30) NOT NULL
);


ALTER TABLE public.transaction_types OWNER TO admin;

--
-- Name: transaction_types_type_id_seq; Type: SEQUENCE; Schema: public; Owner: admin
--

CREATE SEQUENCE public.transaction_types_type_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.transaction_types_type_id_seq OWNER TO admin;

--
-- Name: transaction_types_type_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: admin
--

ALTER SEQUENCE public.transaction_types_type_id_seq OWNED BY public.transaction_types.type_id;


--
-- Name: transactions; Type: TABLE; Schema: public; Owner: admin
--

CREATE TABLE public.transactions (
    transaction_id integer NOT NULL,
    account_id integer NOT NULL,
    destination_account_id integer,
    type_id integer NOT NULL,
    amount numeric(15,2) NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    reference_code character varying(40) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT transactions_amount_check CHECK ((amount > (0)::numeric)),
    CONSTRAINT transactions_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'success'::character varying, 'failed'::character varying])::text[])))
);


ALTER TABLE public.transactions OWNER TO admin;

--
-- Name: transactions_transaction_id_seq; Type: SEQUENCE; Schema: public; Owner: admin
--

CREATE SEQUENCE public.transactions_transaction_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.transactions_transaction_id_seq OWNER TO admin;

--
-- Name: transactions_transaction_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: admin
--

ALTER SEQUENCE public.transactions_transaction_id_seq OWNED BY public.transactions.transaction_id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: admin
--

CREATE TABLE public.users (
    user_id integer NOT NULL,
    full_name character varying(100) NOT NULL,
    email character varying(120) NOT NULL,
    phone_number character varying(20) NOT NULL,
    pin_hash character varying(255) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.users OWNER TO admin;

--
-- Name: users_user_id_seq; Type: SEQUENCE; Schema: public; Owner: admin
--

CREATE SEQUENCE public.users_user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.users_user_id_seq OWNER TO admin;

--
-- Name: users_user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: admin
--

ALTER SEQUENCE public.users_user_id_seq OWNED BY public.users.user_id;


--
-- Name: accounts account_id; Type: DEFAULT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.accounts ALTER COLUMN account_id SET DEFAULT nextval('public.accounts_account_id_seq'::regclass);


--
-- Name: biometric_frames frame_id; Type: DEFAULT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.biometric_frames ALTER COLUMN frame_id SET DEFAULT nextval('public.biometric_frames_frame_id_seq'::regclass);


--
-- Name: merchants merchant_id; Type: DEFAULT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.merchants ALTER COLUMN merchant_id SET DEFAULT nextval('public.merchants_merchant_id_seq'::regclass);


--
-- Name: palm_biometrics biometric_id; Type: DEFAULT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.palm_biometrics ALTER COLUMN biometric_id SET DEFAULT nextval('public.palm_biometrics_biometric_id_seq'::regclass);


--
-- Name: scan_logs log_id; Type: DEFAULT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.scan_logs ALTER COLUMN log_id SET DEFAULT nextval('public.scan_logs_log_id_seq'::regclass);


--
-- Name: transaction_types type_id; Type: DEFAULT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.transaction_types ALTER COLUMN type_id SET DEFAULT nextval('public.transaction_types_type_id_seq'::regclass);


--
-- Name: transactions transaction_id; Type: DEFAULT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.transactions ALTER COLUMN transaction_id SET DEFAULT nextval('public.transactions_transaction_id_seq'::regclass);


--
-- Name: users user_id; Type: DEFAULT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.users ALTER COLUMN user_id SET DEFAULT nextval('public.users_user_id_seq'::regclass);


--
-- Data for Name: accounts; Type: TABLE DATA; Schema: public; Owner: admin
--

COPY public.accounts (account_id, user_id, account_number, balance, created_at) FROM stdin;
\.


--
-- Data for Name: biometric_frames; Type: TABLE DATA; Schema: public; Owner: admin
--

COPY public.biometric_frames (frame_id, biometric_id, embedding_raw, quality_score, captured_at) FROM stdin;
\.


--
-- Data for Name: merchants; Type: TABLE DATA; Schema: public; Owner: admin
--

COPY public.merchants (merchant_id, merchant_name, category, account_id) FROM stdin;
\.


--
-- Data for Name: palm_biometrics; Type: TABLE DATA; Schema: public; Owner: admin
--

COPY public.palm_biometrics (biometric_id, user_id, hand_side, embedding_avg, enrolled_at, is_active) FROM stdin;
\.


--
-- Data for Name: scan_logs; Type: TABLE DATA; Schema: public; Owner: admin
--

COPY public.scan_logs (log_id, user_id, transaction_id, similarity_score, matched, scan_timestamp) FROM stdin;
\.


--
-- Data for Name: transaction_types; Type: TABLE DATA; Schema: public; Owner: admin
--

COPY public.transaction_types (type_id, type_name) FROM stdin;
1	topup
2	transfer
3	payment
4	withdrawal
\.


--
-- Data for Name: transactions; Type: TABLE DATA; Schema: public; Owner: admin
--

COPY public.transactions (transaction_id, account_id, destination_account_id, type_id, amount, status, reference_code, created_at) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: admin
--

COPY public.users (user_id, full_name, email, phone_number, pin_hash, created_at) FROM stdin;
\.


--
-- Name: accounts_account_id_seq; Type: SEQUENCE SET; Schema: public; Owner: admin
--

SELECT pg_catalog.setval('public.accounts_account_id_seq', 1, false);


--
-- Name: biometric_frames_frame_id_seq; Type: SEQUENCE SET; Schema: public; Owner: admin
--

SELECT pg_catalog.setval('public.biometric_frames_frame_id_seq', 1, false);


--
-- Name: merchants_merchant_id_seq; Type: SEQUENCE SET; Schema: public; Owner: admin
--

SELECT pg_catalog.setval('public.merchants_merchant_id_seq', 1, false);


--
-- Name: palm_biometrics_biometric_id_seq; Type: SEQUENCE SET; Schema: public; Owner: admin
--

SELECT pg_catalog.setval('public.palm_biometrics_biometric_id_seq', 1, false);


--
-- Name: scan_logs_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: admin
--

SELECT pg_catalog.setval('public.scan_logs_log_id_seq', 1, false);


--
-- Name: transaction_types_type_id_seq; Type: SEQUENCE SET; Schema: public; Owner: admin
--

SELECT pg_catalog.setval('public.transaction_types_type_id_seq', 4, true);


--
-- Name: transactions_transaction_id_seq; Type: SEQUENCE SET; Schema: public; Owner: admin
--

SELECT pg_catalog.setval('public.transactions_transaction_id_seq', 1, false);


--
-- Name: users_user_id_seq; Type: SEQUENCE SET; Schema: public; Owner: admin
--

SELECT pg_catalog.setval('public.users_user_id_seq', 1, false);


--
-- Name: accounts accounts_account_number_key; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_account_number_key UNIQUE (account_number);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (account_id);


--
-- Name: accounts accounts_user_id_key; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_user_id_key UNIQUE (user_id);


--
-- Name: biometric_frames biometric_frames_pkey; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.biometric_frames
    ADD CONSTRAINT biometric_frames_pkey PRIMARY KEY (frame_id);


--
-- Name: merchants merchants_account_id_key; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.merchants
    ADD CONSTRAINT merchants_account_id_key UNIQUE (account_id);


--
-- Name: merchants merchants_pkey; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.merchants
    ADD CONSTRAINT merchants_pkey PRIMARY KEY (merchant_id);


--
-- Name: palm_biometrics palm_biometrics_pkey; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.palm_biometrics
    ADD CONSTRAINT palm_biometrics_pkey PRIMARY KEY (biometric_id);


--
-- Name: scan_logs scan_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.scan_logs
    ADD CONSTRAINT scan_logs_pkey PRIMARY KEY (log_id);


--
-- Name: transaction_types transaction_types_pkey; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.transaction_types
    ADD CONSTRAINT transaction_types_pkey PRIMARY KEY (type_id);


--
-- Name: transaction_types transaction_types_type_name_key; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.transaction_types
    ADD CONSTRAINT transaction_types_type_name_key UNIQUE (type_name);


--
-- Name: transactions transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (transaction_id);


--
-- Name: transactions transactions_reference_code_key; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_reference_code_key UNIQUE (reference_code);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_phone_number_key; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_phone_number_key UNIQUE (phone_number);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (user_id);


--
-- Name: idx_biometric_frames_biometric; Type: INDEX; Schema: public; Owner: admin
--

CREATE INDEX idx_biometric_frames_biometric ON public.biometric_frames USING btree (biometric_id);


--
-- Name: idx_palm_biometrics_user; Type: INDEX; Schema: public; Owner: admin
--

CREATE INDEX idx_palm_biometrics_user ON public.palm_biometrics USING btree (user_id);


--
-- Name: idx_scan_logs_user; Type: INDEX; Schema: public; Owner: admin
--

CREATE INDEX idx_scan_logs_user ON public.scan_logs USING btree (user_id);


--
-- Name: idx_transactions_account; Type: INDEX; Schema: public; Owner: admin
--

CREATE INDEX idx_transactions_account ON public.transactions USING btree (account_id);


--
-- Name: idx_transactions_dest_account; Type: INDEX; Schema: public; Owner: admin
--

CREATE INDEX idx_transactions_dest_account ON public.transactions USING btree (destination_account_id);


--
-- Name: accounts accounts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: biometric_frames biometric_frames_biometric_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.biometric_frames
    ADD CONSTRAINT biometric_frames_biometric_id_fkey FOREIGN KEY (biometric_id) REFERENCES public.palm_biometrics(biometric_id) ON DELETE CASCADE;


--
-- Name: merchants merchants_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.merchants
    ADD CONSTRAINT merchants_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id) ON DELETE SET NULL;


--
-- Name: palm_biometrics palm_biometrics_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.palm_biometrics
    ADD CONSTRAINT palm_biometrics_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: scan_logs scan_logs_transaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.scan_logs
    ADD CONSTRAINT scan_logs_transaction_id_fkey FOREIGN KEY (transaction_id) REFERENCES public.transactions(transaction_id);


--
-- Name: scan_logs scan_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.scan_logs
    ADD CONSTRAINT scan_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: transactions transactions_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.accounts(account_id);


--
-- Name: transactions transactions_destination_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_destination_account_id_fkey FOREIGN KEY (destination_account_id) REFERENCES public.accounts(account_id);


--
-- Name: transactions transactions_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: admin
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_type_id_fkey FOREIGN KEY (type_id) REFERENCES public.transaction_types(type_id);


--
-- PostgreSQL database dump complete
--

\unrestrict tEWfrVleu8STH4dMmChhTALghA9mfahRvYKchWxwzviM4fu1iUFxYHOm7frnYPT

