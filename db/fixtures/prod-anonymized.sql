--
-- PostgreSQL database dump
--

\restrict 0ZXP3qUXTxWcYDc3HworCnapMyc1yIvpNMoqI41ccURGGGLDaGdHe8ZPW38BSlI

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

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

ALTER TABLE IF EXISTS ONLY public.users_user_permissions DROP CONSTRAINT IF EXISTS users_user_permissions_user_id_92473840_fk_users_id;
ALTER TABLE IF EXISTS ONLY public.users_user_permissions DROP CONSTRAINT IF EXISTS users_user_permissio_permission_id_6d08dcd2_fk_auth_perm;
ALTER TABLE IF EXISTS ONLY public.users_groups DROP CONSTRAINT IF EXISTS users_groups_user_id_f500bee5_fk_users_id;
ALTER TABLE IF EXISTS ONLY public.users_groups DROP CONSTRAINT IF EXISTS users_groups_group_id_2f3517aa_fk_auth_group_id;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_bank_sampah_id_7930af85_fk_bank_sampah_id;
ALTER TABLE IF EXISTS ONLY public.transaksi DROP CONSTRAINT IF EXISTS transaksi_nasabah_id_966cc2f4_fk_nasabah_id;
ALTER TABLE IF EXISTS ONLY public.transaksi DROP CONSTRAINT IF EXISTS transaksi_dicatat_oleh_id_4bbd70d7_fk_users_id;
ALTER TABLE IF EXISTS ONLY public.transaksi DROP CONSTRAINT IF EXISTS transaksi_bank_sampah_id_1dd41faf_fk_bank_sampah_id;
ALTER TABLE IF EXISTS ONLY public.token_blacklist_outstandingtoken DROP CONSTRAINT IF EXISTS token_blacklist_outstandingtoken_user_id_83bc629a_fk_users_id;
ALTER TABLE IF EXISTS ONLY public.token_blacklist_blacklistedtoken DROP CONSTRAINT IF EXISTS token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk;
ALTER TABLE IF EXISTS ONLY public.saldo DROP CONSTRAINT IF EXISTS saldo_nasabah_id_1f6203d1_fk_nasabah_id;
ALTER TABLE IF EXISTS ONLY public.nasabah DROP CONSTRAINT IF EXISTS nasabah_bank_sampah_id_3a17ada0_fk_bank_sampah_id;
ALTER TABLE IF EXISTS ONLY public.jenis_sampah DROP CONSTRAINT IF EXISTS jenis_sampah_bank_sampah_id_cd809894_fk_bank_sampah_id;
ALTER TABLE IF EXISTS ONLY public.django_admin_log DROP CONSTRAINT IF EXISTS django_admin_log_user_id_c564eba6_fk_users_id;
ALTER TABLE IF EXISTS ONLY public.django_admin_log DROP CONSTRAINT IF EXISTS django_admin_log_content_type_id_c4bce8eb_fk_django_co;
ALTER TABLE IF EXISTS ONLY public.detail_transaksi DROP CONSTRAINT IF EXISTS detail_transaksi_transaksi_id_c90d16d8_fk_transaksi_id;
ALTER TABLE IF EXISTS ONLY public.detail_transaksi DROP CONSTRAINT IF EXISTS detail_transaksi_jenis_sampah_id_0192cb92_fk_jenis_sampah_id;
ALTER TABLE IF EXISTS ONLY public.bs_approval_log DROP CONSTRAINT IF EXISTS bs_approval_log_superadmin_id_c3fe1b96_fk_users_id;
ALTER TABLE IF EXISTS ONLY public.bs_approval_log DROP CONSTRAINT IF EXISTS bs_approval_log_bank_sampah_id_6e05394a_fk_bank_sampah_id;
ALTER TABLE IF EXISTS ONLY public.auth_permission DROP CONSTRAINT IF EXISTS auth_permission_content_type_id_2f476e4b_fk_django_co;
ALTER TABLE IF EXISTS ONLY public.auth_group_permissions DROP CONSTRAINT IF EXISTS auth_group_permissions_group_id_b120cbf9_fk_auth_group_id;
ALTER TABLE IF EXISTS ONLY public.auth_group_permissions DROP CONSTRAINT IF EXISTS auth_group_permissio_permission_id_84c5c92e_fk_auth_perm;
DROP INDEX IF EXISTS public.users_user_permissions_user_id_92473840;
DROP INDEX IF EXISTS public.users_user_permissions_permission_id_6d08dcd2;
DROP INDEX IF EXISTS public.users_groups_user_id_f500bee5;
DROP INDEX IF EXISTS public.users_groups_group_id_2f3517aa;
DROP INDEX IF EXISTS public.users_google_id_49fe2bb1_like;
DROP INDEX IF EXISTS public.users_email_0ea73cca_like;
DROP INDEX IF EXISTS public.users_bank_sampah_id_7930af85;
DROP INDEX IF EXISTS public.transaksi_nasabah_id_966cc2f4;
DROP INDEX IF EXISTS public.transaksi_dicatat_oleh_id_4bbd70d7;
DROP INDEX IF EXISTS public.transaksi_bank_sampah_id_1dd41faf;
DROP INDEX IF EXISTS public.token_blacklist_outstandingtoken_user_id_83bc629a;
DROP INDEX IF EXISTS public.token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_like;
DROP INDEX IF EXISTS public.nasabah_bank_sampah_id_3a17ada0;
DROP INDEX IF EXISTS public.jenis_sampah_bank_sampah_id_cd809894;
DROP INDEX IF EXISTS public.django_session_session_key_c0390e0f_like;
DROP INDEX IF EXISTS public.django_session_expire_date_a5c62663;
DROP INDEX IF EXISTS public.django_admin_log_user_id_c564eba6;
DROP INDEX IF EXISTS public.django_admin_log_content_type_id_c4bce8eb;
DROP INDEX IF EXISTS public.detail_transaksi_transaksi_id_c90d16d8;
DROP INDEX IF EXISTS public.detail_transaksi_jenis_sampah_id_0192cb92;
DROP INDEX IF EXISTS public.bs_approval_log_superadmin_id_c3fe1b96;
DROP INDEX IF EXISTS public.bs_approval_log_bank_sampah_id_6e05394a;
DROP INDEX IF EXISTS public.auth_permission_content_type_id_2f476e4b;
DROP INDEX IF EXISTS public.auth_group_permissions_permission_id_84c5c92e;
DROP INDEX IF EXISTS public.auth_group_permissions_group_id_b120cbf9;
DROP INDEX IF EXISTS public.auth_group_name_a6ea08ec_like;
ALTER TABLE IF EXISTS ONLY public.users_user_permissions DROP CONSTRAINT IF EXISTS users_user_permissions_user_id_permission_id_3b86cbdf_uniq;
ALTER TABLE IF EXISTS ONLY public.users_user_permissions DROP CONSTRAINT IF EXISTS users_user_permissions_pkey;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_pkey;
ALTER TABLE IF EXISTS ONLY public.users_groups DROP CONSTRAINT IF EXISTS users_groups_user_id_group_id_fc7788e8_uniq;
ALTER TABLE IF EXISTS ONLY public.users_groups DROP CONSTRAINT IF EXISTS users_groups_pkey;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_google_id_key;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_email_key;
ALTER TABLE IF EXISTS ONLY public.transaksi DROP CONSTRAINT IF EXISTS transaksi_pkey;
ALTER TABLE IF EXISTS ONLY public.token_blacklist_outstandingtoken DROP CONSTRAINT IF EXISTS token_blacklist_outstandingtoken_pkey;
ALTER TABLE IF EXISTS ONLY public.token_blacklist_outstandingtoken DROP CONSTRAINT IF EXISTS token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq;
ALTER TABLE IF EXISTS ONLY public.token_blacklist_blacklistedtoken DROP CONSTRAINT IF EXISTS token_blacklist_blacklistedtoken_token_id_key;
ALTER TABLE IF EXISTS ONLY public.token_blacklist_blacklistedtoken DROP CONSTRAINT IF EXISTS token_blacklist_blacklistedtoken_pkey;
ALTER TABLE IF EXISTS ONLY public.saldo DROP CONSTRAINT IF EXISTS saldo_pkey;
ALTER TABLE IF EXISTS ONLY public.saldo DROP CONSTRAINT IF EXISTS saldo_nasabah_id_key;
ALTER TABLE IF EXISTS ONLY public.nasabah DROP CONSTRAINT IF EXISTS nasabah_pkey;
ALTER TABLE IF EXISTS ONLY public.nasabah DROP CONSTRAINT IF EXISTS nasabah_bank_sampah_id_nomor_4a7bc1d3_uniq;
ALTER TABLE IF EXISTS ONLY public.nasabah DROP CONSTRAINT IF EXISTS nasabah_bank_sampah_id_no_hp_8cfc50f0_uniq;
ALTER TABLE IF EXISTS ONLY public.jenis_sampah DROP CONSTRAINT IF EXISTS jenis_sampah_pkey;
ALTER TABLE IF EXISTS ONLY public.jenis_sampah DROP CONSTRAINT IF EXISTS jenis_sampah_bank_sampah_id_nomor_be7dc933_uniq;
ALTER TABLE IF EXISTS ONLY public.django_session DROP CONSTRAINT IF EXISTS django_session_pkey;
ALTER TABLE IF EXISTS ONLY public.django_migrations DROP CONSTRAINT IF EXISTS django_migrations_pkey;
ALTER TABLE IF EXISTS ONLY public.django_content_type DROP CONSTRAINT IF EXISTS django_content_type_pkey;
ALTER TABLE IF EXISTS ONLY public.django_content_type DROP CONSTRAINT IF EXISTS django_content_type_app_label_model_76bd3d3b_uniq;
ALTER TABLE IF EXISTS ONLY public.django_admin_log DROP CONSTRAINT IF EXISTS django_admin_log_pkey;
ALTER TABLE IF EXISTS ONLY public.detail_transaksi DROP CONSTRAINT IF EXISTS detail_transaksi_pkey;
ALTER TABLE IF EXISTS ONLY public.bs_approval_log DROP CONSTRAINT IF EXISTS bs_approval_log_pkey;
ALTER TABLE IF EXISTS ONLY public.bank_sampah DROP CONSTRAINT IF EXISTS bank_sampah_pkey;
ALTER TABLE IF EXISTS ONLY public.auth_permission DROP CONSTRAINT IF EXISTS auth_permission_pkey;
ALTER TABLE IF EXISTS ONLY public.auth_permission DROP CONSTRAINT IF EXISTS auth_permission_content_type_id_codename_01ab375a_uniq;
ALTER TABLE IF EXISTS ONLY public.auth_group DROP CONSTRAINT IF EXISTS auth_group_pkey;
ALTER TABLE IF EXISTS ONLY public.auth_group_permissions DROP CONSTRAINT IF EXISTS auth_group_permissions_pkey;
ALTER TABLE IF EXISTS ONLY public.auth_group_permissions DROP CONSTRAINT IF EXISTS auth_group_permissions_group_id_permission_id_0cd325b0_uniq;
ALTER TABLE IF EXISTS ONLY public.auth_group DROP CONSTRAINT IF EXISTS auth_group_name_key;
DROP TABLE IF EXISTS public.users_user_permissions;
DROP TABLE IF EXISTS public.users_groups;
DROP TABLE IF EXISTS public.users;
DROP TABLE IF EXISTS public.transaksi;
DROP TABLE IF EXISTS public.token_blacklist_outstandingtoken;
DROP TABLE IF EXISTS public.token_blacklist_blacklistedtoken;
DROP TABLE IF EXISTS public.saldo;
DROP TABLE IF EXISTS public.nasabah;
DROP TABLE IF EXISTS public.jenis_sampah;
DROP TABLE IF EXISTS public.django_session;
DROP TABLE IF EXISTS public.django_migrations;
DROP TABLE IF EXISTS public.django_content_type;
DROP TABLE IF EXISTS public.django_admin_log;
DROP TABLE IF EXISTS public.detail_transaksi;
DROP TABLE IF EXISTS public.bs_approval_log;
DROP TABLE IF EXISTS public.bank_sampah;
DROP TABLE IF EXISTS public.auth_permission;
DROP TABLE IF EXISTS public.auth_group_permissions;
DROP TABLE IF EXISTS public.auth_group;
SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: auth_group; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group (
    id integer NOT NULL,
    name character varying(150) NOT NULL
);


--
-- Name: auth_group_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_group_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group_permissions (
    id bigint NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_permission (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    codename character varying(100) NOT NULL
);


--
-- Name: auth_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_permission ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_permission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: bank_sampah; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bank_sampah (
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    nama character varying(150) NOT NULL,
    alamat text NOT NULL,
    kota character varying(100) NOT NULL,
    no_hp_pic character varying(20) NOT NULL,
    wa_gateway_token text,
    wa_template text NOT NULL,
    foto_logo character varying(100) NOT NULL,
    foto_kegiatan character varying(100) NOT NULL,
    status character varying(20) NOT NULL,
    invite_token character varying(120) NOT NULL,
    invite_token_expires timestamp with time zone,
    is_active boolean NOT NULL
);


--
-- Name: bs_approval_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bs_approval_log (
    id uuid NOT NULL,
    status character varying(20) NOT NULL,
    catatan text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    bank_sampah_id uuid NOT NULL,
    superadmin_id uuid NOT NULL
);


--
-- Name: detail_transaksi; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.detail_transaksi (
    id uuid NOT NULL,
    nama_sampah_snapshot character varying(50) NOT NULL,
    kategori_snapshot character varying(20) NOT NULL,
    harga_snapshot numeric(11,2) NOT NULL,
    berat numeric(10,3) NOT NULL,
    subtotal numeric(14,2) NOT NULL,
    jenis_sampah_id uuid NOT NULL,
    transaksi_id uuid NOT NULL
);


--
-- Name: django_admin_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_admin_log (
    id integer NOT NULL,
    action_time timestamp with time zone NOT NULL,
    object_id text,
    object_repr character varying(200) NOT NULL,
    action_flag smallint NOT NULL,
    change_message text NOT NULL,
    content_type_id integer,
    user_id uuid NOT NULL,
    CONSTRAINT django_admin_log_action_flag_check CHECK ((action_flag >= 0))
);


--
-- Name: django_admin_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_admin_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_admin_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_content_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


--
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_content_type ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_content_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_migrations (
    id bigint NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


--
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_migrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL
);


--
-- Name: jenis_sampah; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jenis_sampah (
    id uuid NOT NULL,
    nomor character varying(30) NOT NULL,
    nama_sampah character varying(50) NOT NULL,
    kategori character varying(20) NOT NULL,
    deskripsi text NOT NULL,
    harga_per_kg numeric(11,2) NOT NULL,
    is_active boolean NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    bank_sampah_id uuid NOT NULL
);


--
-- Name: nasabah; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nasabah (
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    nomor character varying(30) NOT NULL,
    nama character varying(100) NOT NULL,
    jenis_kelamin character varying(20) NOT NULL,
    tanggal_lahir date,
    alamat text NOT NULL,
    no_hp character varying(20) NOT NULL,
    tanggal_daftar date NOT NULL,
    is_active boolean NOT NULL,
    bank_sampah_id uuid NOT NULL
);


--
-- Name: saldo; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.saldo (
    id uuid NOT NULL,
    total_saldo numeric(14,2) NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    nasabah_id uuid NOT NULL
);


--
-- Name: token_blacklist_blacklistedtoken; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.token_blacklist_blacklistedtoken (
    id bigint NOT NULL,
    blacklisted_at timestamp with time zone NOT NULL,
    token_id bigint NOT NULL
);


--
-- Name: token_blacklist_blacklistedtoken_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.token_blacklist_blacklistedtoken ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.token_blacklist_blacklistedtoken_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: token_blacklist_outstandingtoken; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.token_blacklist_outstandingtoken (
    id bigint NOT NULL,
    token text NOT NULL,
    created_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    user_id uuid,
    jti character varying(255) NOT NULL
);


--
-- Name: token_blacklist_outstandingtoken_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.token_blacklist_outstandingtoken ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.token_blacklist_outstandingtoken_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: transaksi; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transaksi (
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    tanggal timestamp with time zone NOT NULL,
    total_nilai numeric(14,2) NOT NULL,
    tipe character varying(20) NOT NULL,
    catatan text,
    status_wa character varying(20) NOT NULL,
    bank_sampah_id uuid NOT NULL,
    dicatat_oleh_id uuid NOT NULL,
    nasabah_id uuid NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    is_superuser boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    google_id character varying(255),
    email character varying(254) NOT NULL,
    nama character varying(150) NOT NULL,
    no_hp character varying(20) NOT NULL,
    jenis_kelamin character varying(20) NOT NULL,
    tanggal_lahir date,
    role character varying(20) NOT NULL,
    is_profile_complete boolean NOT NULL,
    is_active boolean NOT NULL,
    is_staff boolean NOT NULL,
    bank_sampah_id uuid,
    is_primary_pengelola boolean NOT NULL
);


--
-- Name: users_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users_groups (
    id bigint NOT NULL,
    user_id uuid NOT NULL,
    group_id integer NOT NULL
);


--
-- Name: users_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.users_groups ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.users_groups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: users_user_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users_user_permissions (
    id bigint NOT NULL,
    user_id uuid NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: users_user_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.users_user_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.users_user_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Data for Name: auth_group; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.auth_group (id, name) FROM stdin;
\.


--
-- Data for Name: auth_group_permissions; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.auth_group_permissions (id, group_id, permission_id) FROM stdin;
\.


--
-- Data for Name: auth_permission; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.auth_permission (id, name, content_type_id, codename) FROM stdin;
1	Can add log entry	1	add_logentry
2	Can change log entry	1	change_logentry
3	Can delete log entry	1	delete_logentry
4	Can view log entry	1	view_logentry
5	Can add permission	3	add_permission
6	Can change permission	3	change_permission
7	Can delete permission	3	delete_permission
8	Can view permission	3	view_permission
9	Can add group	2	add_group
10	Can change group	2	change_group
11	Can delete group	2	delete_group
12	Can view group	2	view_group
13	Can add content type	4	add_contenttype
14	Can change content type	4	change_contenttype
15	Can delete content type	4	delete_contenttype
16	Can view content type	4	view_contenttype
17	Can add session	5	add_session
18	Can change session	5	change_session
19	Can delete session	5	delete_session
20	Can view session	5	view_session
21	Can add Outstanding Token	7	add_outstandingtoken
22	Can change Outstanding Token	7	change_outstandingtoken
23	Can delete Outstanding Token	7	delete_outstandingtoken
24	Can view Outstanding Token	7	view_outstandingtoken
25	Can add Blacklisted Token	6	add_blacklistedtoken
26	Can change Blacklisted Token	6	change_blacklistedtoken
27	Can delete Blacklisted Token	6	delete_blacklistedtoken
28	Can view Blacklisted Token	6	view_blacklistedtoken
29	Can add bank sampah	8	add_banksampah
30	Can change bank sampah	8	change_banksampah
31	Can delete bank sampah	8	delete_banksampah
32	Can view bank sampah	8	view_banksampah
33	Can add user	15	add_user
34	Can change user	15	change_user
35	Can delete user	15	delete_user
36	Can view user	15	view_user
37	Can add nasabah	12	add_nasabah
38	Can change nasabah	12	change_nasabah
39	Can delete nasabah	12	delete_nasabah
40	Can view nasabah	12	view_nasabah
41	Can add saldo	13	add_saldo
42	Can change saldo	13	change_saldo
43	Can delete saldo	13	delete_saldo
44	Can view saldo	13	view_saldo
45	Can add jenis sampah	11	add_jenissampah
46	Can change jenis sampah	11	change_jenissampah
47	Can delete jenis sampah	11	delete_jenissampah
48	Can view jenis sampah	11	view_jenissampah
49	Can add transaksi	14	add_transaksi
50	Can change transaksi	14	change_transaksi
51	Can delete transaksi	14	delete_transaksi
52	Can view transaksi	14	view_transaksi
53	Can add detail transaksi	10	add_detailtransaksi
54	Can change detail transaksi	10	change_detailtransaksi
55	Can delete detail transaksi	10	delete_detailtransaksi
56	Can view detail transaksi	10	view_detailtransaksi
57	Can add bank sampah approval log	9	add_banksampahapprovallog
58	Can change bank sampah approval log	9	change_banksampahapprovallog
59	Can delete bank sampah approval log	9	delete_banksampahapprovallog
60	Can view bank sampah approval log	9	view_banksampahapprovallog
\.


--
-- Data for Name: bank_sampah; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.bank_sampah (created_at, updated_at, id, nama, alamat, kota, no_hp_pic, wa_gateway_token, wa_template, foto_logo, foto_kegiatan, status, invite_token, invite_token_expires, is_active) FROM stdin;
2026-08-22 15:49:56.357395+00	2026-08-24 10:23:48.463321+00	75f3940b-df44-4180-9e5e-3a41193317b0	Bank Sampah Anonim 1	Jl. Contoh No. 1		+62810000001	\N	Halo {Nama}, setoran sampahmu senilai {Total} sudah kami catat ya.\nSaldo tabunganmu sekarang adalah Rp {Saldo}.\n{daftar_item}\nTerima kasih! 🌿			active	anon-invite-1	2026-08-27 10:23:48.46322+00	t
2026-08-25 03:32:14.523837+00	2026-08-25 03:55:03.44482+00	a8fbf29d-c419-421a-86b7-70bbd0694eae	Bank Sampah Anonim 2	Jl. Contoh No. 2		+62810000002	\N	Halo {Nama}, setoran sampahmu senilai {Total} sudah kami catat ya.\nSaldo tabunganmu sekarang adalah Rp {Saldo}.\n{daftar_item}\nTerima kasih! 🌿			active		\N	t
2026-09-07 11:54:13.141047+00	2026-09-07 12:47:54.844501+00	02508297-dd86-4dc5-8326-986429575bcd	Bank Sampah Anonim 3	Jl. Contoh No. 3		+62810000003	\N	Halo {Nama}, setoran sampahmu senilai {Total} sudah kami catat ya.\nSaldo tabunganmu sekarang adalah Rp {Saldo}.\n{daftar_item}\nTerima kasih! 🌿			active		\N	t
\.


--
-- Data for Name: bs_approval_log; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.bs_approval_log (id, status, catatan, created_at, bank_sampah_id, superadmin_id) FROM stdin;
d23d924f-9238-4d6a-a066-f85a7d30fe21	approved		2026-08-23 11:36:53.515671+00	75f3940b-df44-4180-9e5e-3a41193317b0	f394c5b6-e2dd-4416-81b7-9939a486f90a
6fb07d0e-a878-470e-bfbd-4489d3212f67	approved		2026-08-25 03:55:03.451678+00	a8fbf29d-c419-421a-86b7-70bbd0694eae	f394c5b6-e2dd-4416-81b7-9939a486f90a
ce627cae-9b1c-4a7a-aa8e-f45ae434b2a4	approved		2026-09-07 12:36:45.223418+00	02508297-dd86-4dc5-8326-986429575bcd	f394c5b6-e2dd-4416-81b7-9939a486f90a
\.


--
-- Data for Name: detail_transaksi; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.detail_transaksi (id, nama_sampah_snapshot, kategori_snapshot, harga_snapshot, berat, subtotal, jenis_sampah_id, transaksi_id) FROM stdin;
\.


--
-- Data for Name: django_admin_log; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.django_admin_log (id, action_time, object_id, object_repr, action_flag, change_message, content_type_id, user_id) FROM stdin;
\.


--
-- Data for Name: django_content_type; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.django_content_type (id, app_label, model) FROM stdin;
1	admin	logentry
2	auth	group
3	auth	permission
4	contenttypes	contenttype
5	sessions	session
6	token_blacklist	blacklistedtoken
7	token_blacklist	outstandingtoken
8	api	banksampah
9	api	banksampahapprovallog
10	api	detailtransaksi
11	api	jenissampah
12	api	nasabah
13	api	saldo
14	api	transaksi
15	api	user
\.


--
-- Data for Name: django_migrations; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.django_migrations (id, app, name, applied) FROM stdin;
1	contenttypes	0001_initial	2026-07-08 14:22:39.198485+00
2	contenttypes	0002_remove_content_type_name	2026-07-08 14:22:39.218016+00
3	auth	0001_initial	2026-07-08 14:22:39.303388+00
4	auth	0002_alter_permission_name_max_length	2026-07-08 14:22:39.31698+00
5	auth	0003_alter_user_email_max_length	2026-07-08 14:22:39.326583+00
6	auth	0004_alter_user_username_opts	2026-07-08 14:22:39.337831+00
7	auth	0005_alter_user_last_login_null	2026-07-08 14:22:39.349687+00
8	auth	0006_require_contenttypes_0002	2026-07-08 14:22:39.358303+00
9	auth	0007_alter_validators_add_error_messages	2026-07-08 14:22:39.369367+00
10	auth	0008_alter_user_username_max_length	2026-07-08 14:22:39.380518+00
11	auth	0009_alter_user_last_name_max_length	2026-07-08 14:22:39.392211+00
12	auth	0010_alter_group_name_max_length	2026-07-08 14:22:39.408873+00
13	auth	0011_update_proxy_permissions	2026-07-08 14:22:39.41816+00
14	auth	0012_alter_user_first_name_max_length	2026-07-08 14:22:39.429852+00
15	api	0001_initial	2026-07-08 14:22:39.746643+00
16	admin	0001_initial	2026-07-08 14:22:39.793862+00
17	admin	0002_logentry_remove_auto_add	2026-07-08 14:22:39.8044+00
18	admin	0003_logentry_add_action_flag_choices	2026-07-08 14:22:39.819834+00
19	api	0002_user_is_primary_pengelola	2026-07-08 14:22:39.845293+00
20	api	0003_alter_banksampah_foto_kegiatan_and_more	2026-07-08 14:22:39.911815+00
21	sessions	0001_initial	2026-07-08 14:22:39.944604+00
22	token_blacklist	0001_initial	2026-07-08 14:22:40.007343+00
23	token_blacklist	0002_outstandingtoken_jti_hex	2026-07-08 14:22:40.024773+00
24	token_blacklist	0003_auto_20171017_2007	2026-07-08 14:22:40.052991+00
25	token_blacklist	0004_auto_20171017_2013	2026-07-08 14:22:40.082598+00
26	token_blacklist	0005_remove_outstandingtoken_jti	2026-07-08 14:22:40.101585+00
27	token_blacklist	0006_auto_20171017_2113	2026-07-08 14:22:40.121413+00
28	token_blacklist	0007_auto_20171017_2214	2026-07-08 14:22:40.172966+00
29	token_blacklist	0008_migrate_to_bigautofield	2026-07-08 14:22:40.25915+00
30	token_blacklist	0010_fix_migrate_to_bigautofield	2026-07-08 14:22:40.281686+00
31	token_blacklist	0011_linearizes_history	2026-07-08 14:22:40.290794+00
32	token_blacklist	0012_alter_outstandingtoken_user	2026-07-08 14:22:40.310699+00
33	token_blacklist	0013_alter_blacklistedtoken_options_and_more	2026-07-08 14:22:40.329981+00
34	api	0004_alter_banksampah_foto_logo	2026-07-21 05:32:53.094846+00
\.


--
-- Data for Name: django_session; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.django_session (session_key, session_data, expire_date) FROM stdin;
\.


--
-- Data for Name: jenis_sampah; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.jenis_sampah (id, nomor, nama_sampah, kategori, deskripsi, harga_per_kg, is_active, updated_at, bank_sampah_id) FROM stdin;
\.


--
-- Data for Name: nasabah; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.nasabah (created_at, updated_at, id, nomor, nama, jenis_kelamin, tanggal_lahir, alamat, no_hp, tanggal_daftar, is_active, bank_sampah_id) FROM stdin;
\.


--
-- Data for Name: saldo; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.saldo (id, total_saldo, updated_at, nasabah_id) FROM stdin;
\.


--
-- Data for Name: token_blacklist_blacklistedtoken; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.token_blacklist_blacklistedtoken (id, blacklisted_at, token_id) FROM stdin;
\.


--
-- Data for Name: token_blacklist_outstandingtoken; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.token_blacklist_outstandingtoken (id, token, created_at, expires_at, user_id, jti) FROM stdin;
\.


--
-- Data for Name: transaksi; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.transaksi (created_at, updated_at, id, tanggal, total_nilai, tipe, catatan, status_wa, bank_sampah_id, dicatat_oleh_id, nasabah_id) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.users (password, last_login, is_superuser, created_at, updated_at, id, google_id, email, nama, no_hp, jenis_kelamin, tanggal_lahir, role, is_profile_complete, is_active, is_staff, bank_sampah_id, is_primary_pengelola) FROM stdin;
!	\N	f	2026-08-21 17:50:43.109218+00	2026-08-21 17:50:43.109229+00	171346e0-e224-4e34-be91-3c516d1816ec	anon-google-01	user01@example.invalid	Pengguna Anonim 1			\N	pengelola	f	t	f	\N	f
!	\N	f	2026-08-21 17:50:55.320998+00	2026-08-21 17:50:55.321006+00	031c50be-c92c-403b-8a8f-edc258471c50	anon-google-02	user02@example.invalid	Pengguna Anonim 2			\N	pengelola	f	t	f	\N	f
!	\N	f	2026-08-22 04:31:59.726215+00	2026-08-22 04:31:59.726235+00	fc374862-abf3-4965-8abb-6c16c83ff817	anon-google-03	user03@example.invalid	Pengguna Anonim 3			\N	pengelola	f	t	f	\N	f
!	\N	f	2026-08-22 15:48:58.705285+00	2026-08-22 15:49:56.364557+00	83c55116-bb33-423c-ae3f-1454b6470548	anon-google-04	user04@example.invalid	Pengguna Anonim 4	+62800000004	perempuan	1990-01-04	pengelola	t	t	f	75f3940b-df44-4180-9e5e-3a41193317b0	t
!	\N	f	2026-08-23 12:08:44.446025+00	2026-08-23 12:08:44.44604+00	72dfeb8c-57e9-453f-b352-c92656bd7248	anon-google-05	user05@example.invalid	Pengguna Anonim 5			\N	pengelola	f	t	f	\N	f
!	\N	f	2026-08-24 10:23:36.716569+00	2026-08-24 10:23:36.716578+00	b5bbaeb9-862d-4fdf-95dc-df94b0502e76	anon-google-06	user06@example.invalid	Pengguna Anonim 6			\N	pengelola	f	t	f	\N	f
!	\N	f	2026-08-24 10:24:20.096454+00	2026-08-24 10:24:44.607201+00	b2142f7f-c23e-4fff-ada9-eef06ebd49aa	anon-google-07	user07@example.invalid	Pengguna Anonim 7	+62800000007	laki-laki	1990-01-07	pengelola	t	t	f	75f3940b-df44-4180-9e5e-3a41193317b0	f
!	\N	f	2026-08-25 03:29:44.410394+00	2026-08-25 03:32:14.530568+00	077ed5a6-7125-49f0-b49c-1c2512039ee0	anon-google-08	user08@example.invalid	Pengguna Anonim 8	+62800000008	perempuan	1990-01-08	pengelola	t	t	f	a8fbf29d-c419-421a-86b7-70bbd0694eae	t
!	\N	f	2026-08-25 13:08:34.333367+00	2026-08-25 13:08:34.333378+00	eb333ef5-5a8e-48ab-bbd0-532dd46c5050	anon-google-09	user09@example.invalid	Pengguna Anonim 9			\N	pengelola	f	t	f	\N	f
!	\N	f	2026-08-28 06:55:54.804883+00	2026-08-28 06:55:54.804894+00	cb6db61b-9c62-49db-b596-9bfc73548d48	anon-google-10	user10@example.invalid	Pengguna Anonim 10			\N	pengelola	f	t	f	\N	f
!	\N	f	2026-09-07 11:53:07.73512+00	2026-09-07 11:54:13.149678+00	d2a676dc-87a7-4812-aa8f-f8a58acc6647	anon-google-11	user11@example.invalid	Pengguna Anonim 11	+62800000011	laki-laki	1990-01-11	pengelola	t	t	f	02508297-dd86-4dc5-8326-986429575bcd	t
!	\N	f	2026-09-07 12:00:08.791323+00	2026-09-07 12:00:08.791334+00	d6817883-8f6b-47a1-923d-a17d3856f9b5	anon-google-12	user12@example.invalid	Pengguna Anonim 12			\N	pengelola	f	t	f	\N	f
!	\N	t	2026-08-22 15:50:05.650624+00	2026-08-23 11:09:40.366863+00	f394c5b6-e2dd-4416-81b7-9939a486f90a	anon-google-13	user13@example.invalid	Pengguna Anonim 13			\N	superadmin	t	t	t	\N	f
!	\N	f	2026-09-14 12:39:58.187237+00	2026-09-14 12:39:58.187249+00	fa7c654f-9401-4902-aaf4-78da71b97c50	anon-google-14	user14@example.invalid	Pengguna Anonim 14			\N	pengelola	f	t	f	\N	f
!	\N	f	2026-09-14 23:05:46.121439+00	2026-09-14 23:05:46.121452+00	619e75e9-9e9c-4450-b94f-b1d5aa9fded0	anon-google-15	user15@example.invalid	Pengguna Anonim 15			\N	pengelola	f	t	f	\N	f
\.


--
-- Data for Name: users_groups; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.users_groups (id, user_id, group_id) FROM stdin;
\.


--
-- Data for Name: users_user_permissions; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.users_user_permissions (id, user_id, permission_id) FROM stdin;
\.


--
-- Name: auth_group_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.auth_group_id_seq', 1, false);


--
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.auth_group_permissions_id_seq', 1, false);


--
-- Name: auth_permission_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.auth_permission_id_seq', 60, true);


--
-- Name: django_admin_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.django_admin_log_id_seq', 1, false);


--
-- Name: django_content_type_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.django_content_type_id_seq', 15, true);


--
-- Name: django_migrations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.django_migrations_id_seq', 34, true);


--
-- Name: token_blacklist_blacklistedtoken_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.token_blacklist_blacklistedtoken_id_seq', 17, true);


--
-- Name: token_blacklist_outstandingtoken_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.token_blacklist_outstandingtoken_id_seq', 27, true);


--
-- Name: users_groups_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.users_groups_id_seq', 1, false);


--
-- Name: users_user_permissions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.users_user_permissions_id_seq', 1, false);


--
-- Name: auth_group auth_group_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_name_key UNIQUE (name);


--
-- Name: auth_group_permissions auth_group_permissions_group_id_permission_id_0cd325b0_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id);


--
-- Name: auth_group_permissions auth_group_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_group auth_group_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_pkey PRIMARY KEY (id);


--
-- Name: auth_permission auth_permission_content_type_id_codename_01ab375a_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename);


--
-- Name: auth_permission auth_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_pkey PRIMARY KEY (id);


--
-- Name: bank_sampah bank_sampah_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_sampah
    ADD CONSTRAINT bank_sampah_pkey PRIMARY KEY (id);


--
-- Name: bs_approval_log bs_approval_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bs_approval_log
    ADD CONSTRAINT bs_approval_log_pkey PRIMARY KEY (id);


--
-- Name: detail_transaksi detail_transaksi_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detail_transaksi
    ADD CONSTRAINT detail_transaksi_pkey PRIMARY KEY (id);


--
-- Name: django_admin_log django_admin_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_pkey PRIMARY KEY (id);


--
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- Name: django_session django_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_session
    ADD CONSTRAINT django_session_pkey PRIMARY KEY (session_key);


--
-- Name: jenis_sampah jenis_sampah_bank_sampah_id_nomor_be7dc933_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenis_sampah
    ADD CONSTRAINT jenis_sampah_bank_sampah_id_nomor_be7dc933_uniq UNIQUE (bank_sampah_id, nomor);


--
-- Name: jenis_sampah jenis_sampah_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenis_sampah
    ADD CONSTRAINT jenis_sampah_pkey PRIMARY KEY (id);


--
-- Name: nasabah nasabah_bank_sampah_id_no_hp_8cfc50f0_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nasabah
    ADD CONSTRAINT nasabah_bank_sampah_id_no_hp_8cfc50f0_uniq UNIQUE (bank_sampah_id, no_hp);


--
-- Name: nasabah nasabah_bank_sampah_id_nomor_4a7bc1d3_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nasabah
    ADD CONSTRAINT nasabah_bank_sampah_id_nomor_4a7bc1d3_uniq UNIQUE (bank_sampah_id, nomor);


--
-- Name: nasabah nasabah_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nasabah
    ADD CONSTRAINT nasabah_pkey PRIMARY KEY (id);


--
-- Name: saldo saldo_nasabah_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saldo
    ADD CONSTRAINT saldo_nasabah_id_key UNIQUE (nasabah_id);


--
-- Name: saldo saldo_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saldo
    ADD CONSTRAINT saldo_pkey PRIMARY KEY (id);


--
-- Name: token_blacklist_blacklistedtoken token_blacklist_blacklistedtoken_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_blacklistedtoken
    ADD CONSTRAINT token_blacklist_blacklistedtoken_pkey PRIMARY KEY (id);


--
-- Name: token_blacklist_blacklistedtoken token_blacklist_blacklistedtoken_token_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_blacklistedtoken
    ADD CONSTRAINT token_blacklist_blacklistedtoken_token_id_key UNIQUE (token_id);


--
-- Name: token_blacklist_outstandingtoken token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_outstandingtoken
    ADD CONSTRAINT token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq UNIQUE (jti);


--
-- Name: token_blacklist_outstandingtoken token_blacklist_outstandingtoken_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_outstandingtoken
    ADD CONSTRAINT token_blacklist_outstandingtoken_pkey PRIMARY KEY (id);


--
-- Name: transaksi transaksi_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaksi
    ADD CONSTRAINT transaksi_pkey PRIMARY KEY (id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_google_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_google_id_key UNIQUE (google_id);


--
-- Name: users_groups users_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users_groups
    ADD CONSTRAINT users_groups_pkey PRIMARY KEY (id);


--
-- Name: users_groups users_groups_user_id_group_id_fc7788e8_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users_groups
    ADD CONSTRAINT users_groups_user_id_group_id_fc7788e8_uniq UNIQUE (user_id, group_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users_user_permissions users_user_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users_user_permissions
    ADD CONSTRAINT users_user_permissions_pkey PRIMARY KEY (id);


--
-- Name: users_user_permissions users_user_permissions_user_id_permission_id_3b86cbdf_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users_user_permissions
    ADD CONSTRAINT users_user_permissions_user_id_permission_id_3b86cbdf_uniq UNIQUE (user_id, permission_id);


--
-- Name: auth_group_name_a6ea08ec_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops);


--
-- Name: auth_group_permissions_group_id_b120cbf9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id);


--
-- Name: auth_group_permissions_permission_id_84c5c92e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id);


--
-- Name: auth_permission_content_type_id_2f476e4b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id);


--
-- Name: bs_approval_log_bank_sampah_id_6e05394a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX bs_approval_log_bank_sampah_id_6e05394a ON public.bs_approval_log USING btree (bank_sampah_id);


--
-- Name: bs_approval_log_superadmin_id_c3fe1b96; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX bs_approval_log_superadmin_id_c3fe1b96 ON public.bs_approval_log USING btree (superadmin_id);


--
-- Name: detail_transaksi_jenis_sampah_id_0192cb92; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX detail_transaksi_jenis_sampah_id_0192cb92 ON public.detail_transaksi USING btree (jenis_sampah_id);


--
-- Name: detail_transaksi_transaksi_id_c90d16d8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX detail_transaksi_transaksi_id_c90d16d8 ON public.detail_transaksi USING btree (transaksi_id);


--
-- Name: django_admin_log_content_type_id_c4bce8eb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_admin_log_content_type_id_c4bce8eb ON public.django_admin_log USING btree (content_type_id);


--
-- Name: django_admin_log_user_id_c564eba6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_admin_log_user_id_c564eba6 ON public.django_admin_log USING btree (user_id);


--
-- Name: django_session_expire_date_a5c62663; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);


--
-- Name: django_session_session_key_c0390e0f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


--
-- Name: jenis_sampah_bank_sampah_id_cd809894; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX jenis_sampah_bank_sampah_id_cd809894 ON public.jenis_sampah USING btree (bank_sampah_id);


--
-- Name: nasabah_bank_sampah_id_3a17ada0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX nasabah_bank_sampah_id_3a17ada0 ON public.nasabah USING btree (bank_sampah_id);


--
-- Name: token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_like ON public.token_blacklist_outstandingtoken USING btree (jti varchar_pattern_ops);


--
-- Name: token_blacklist_outstandingtoken_user_id_83bc629a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX token_blacklist_outstandingtoken_user_id_83bc629a ON public.token_blacklist_outstandingtoken USING btree (user_id);


--
-- Name: transaksi_bank_sampah_id_1dd41faf; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX transaksi_bank_sampah_id_1dd41faf ON public.transaksi USING btree (bank_sampah_id);


--
-- Name: transaksi_dicatat_oleh_id_4bbd70d7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX transaksi_dicatat_oleh_id_4bbd70d7 ON public.transaksi USING btree (dicatat_oleh_id);


--
-- Name: transaksi_nasabah_id_966cc2f4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX transaksi_nasabah_id_966cc2f4 ON public.transaksi USING btree (nasabah_id);


--
-- Name: users_bank_sampah_id_7930af85; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX users_bank_sampah_id_7930af85 ON public.users USING btree (bank_sampah_id);


--
-- Name: users_email_0ea73cca_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX users_email_0ea73cca_like ON public.users USING btree (email varchar_pattern_ops);


--
-- Name: users_google_id_49fe2bb1_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX users_google_id_49fe2bb1_like ON public.users USING btree (google_id varchar_pattern_ops);


--
-- Name: users_groups_group_id_2f3517aa; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX users_groups_group_id_2f3517aa ON public.users_groups USING btree (group_id);


--
-- Name: users_groups_user_id_f500bee5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX users_groups_user_id_f500bee5 ON public.users_groups USING btree (user_id);


--
-- Name: users_user_permissions_permission_id_6d08dcd2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX users_user_permissions_permission_id_6d08dcd2 ON public.users_user_permissions USING btree (permission_id);


--
-- Name: users_user_permissions_user_id_92473840; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX users_user_permissions_user_id_92473840 ON public.users_user_permissions USING btree (user_id);


--
-- Name: auth_group_permissions auth_group_permissio_permission_id_84c5c92e_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_group_permissions auth_group_permissions_group_id_b120cbf9_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_permission auth_permission_content_type_id_2f476e4b_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: bs_approval_log bs_approval_log_bank_sampah_id_6e05394a_fk_bank_sampah_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bs_approval_log
    ADD CONSTRAINT bs_approval_log_bank_sampah_id_6e05394a_fk_bank_sampah_id FOREIGN KEY (bank_sampah_id) REFERENCES public.bank_sampah(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: bs_approval_log bs_approval_log_superadmin_id_c3fe1b96_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bs_approval_log
    ADD CONSTRAINT bs_approval_log_superadmin_id_c3fe1b96_fk_users_id FOREIGN KEY (superadmin_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: detail_transaksi detail_transaksi_jenis_sampah_id_0192cb92_fk_jenis_sampah_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detail_transaksi
    ADD CONSTRAINT detail_transaksi_jenis_sampah_id_0192cb92_fk_jenis_sampah_id FOREIGN KEY (jenis_sampah_id) REFERENCES public.jenis_sampah(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: detail_transaksi detail_transaksi_transaksi_id_c90d16d8_fk_transaksi_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detail_transaksi
    ADD CONSTRAINT detail_transaksi_transaksi_id_c90d16d8_fk_transaksi_id FOREIGN KEY (transaksi_id) REFERENCES public.transaksi(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_admin_log django_admin_log_content_type_id_c4bce8eb_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_content_type_id_c4bce8eb_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_admin_log django_admin_log_user_id_c564eba6_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_user_id_c564eba6_fk_users_id FOREIGN KEY (user_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: jenis_sampah jenis_sampah_bank_sampah_id_cd809894_fk_bank_sampah_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenis_sampah
    ADD CONSTRAINT jenis_sampah_bank_sampah_id_cd809894_fk_bank_sampah_id FOREIGN KEY (bank_sampah_id) REFERENCES public.bank_sampah(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: nasabah nasabah_bank_sampah_id_3a17ada0_fk_bank_sampah_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nasabah
    ADD CONSTRAINT nasabah_bank_sampah_id_3a17ada0_fk_bank_sampah_id FOREIGN KEY (bank_sampah_id) REFERENCES public.bank_sampah(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: saldo saldo_nasabah_id_1f6203d1_fk_nasabah_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saldo
    ADD CONSTRAINT saldo_nasabah_id_1f6203d1_fk_nasabah_id FOREIGN KEY (nasabah_id) REFERENCES public.nasabah(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: token_blacklist_blacklistedtoken token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_blacklistedtoken
    ADD CONSTRAINT token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk FOREIGN KEY (token_id) REFERENCES public.token_blacklist_outstandingtoken(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: token_blacklist_outstandingtoken token_blacklist_outstandingtoken_user_id_83bc629a_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_outstandingtoken
    ADD CONSTRAINT token_blacklist_outstandingtoken_user_id_83bc629a_fk_users_id FOREIGN KEY (user_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: transaksi transaksi_bank_sampah_id_1dd41faf_fk_bank_sampah_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaksi
    ADD CONSTRAINT transaksi_bank_sampah_id_1dd41faf_fk_bank_sampah_id FOREIGN KEY (bank_sampah_id) REFERENCES public.bank_sampah(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: transaksi transaksi_dicatat_oleh_id_4bbd70d7_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaksi
    ADD CONSTRAINT transaksi_dicatat_oleh_id_4bbd70d7_fk_users_id FOREIGN KEY (dicatat_oleh_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: transaksi transaksi_nasabah_id_966cc2f4_fk_nasabah_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaksi
    ADD CONSTRAINT transaksi_nasabah_id_966cc2f4_fk_nasabah_id FOREIGN KEY (nasabah_id) REFERENCES public.nasabah(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: users users_bank_sampah_id_7930af85_fk_bank_sampah_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_bank_sampah_id_7930af85_fk_bank_sampah_id FOREIGN KEY (bank_sampah_id) REFERENCES public.bank_sampah(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: users_groups users_groups_group_id_2f3517aa_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users_groups
    ADD CONSTRAINT users_groups_group_id_2f3517aa_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: users_groups users_groups_user_id_f500bee5_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users_groups
    ADD CONSTRAINT users_groups_user_id_f500bee5_fk_users_id FOREIGN KEY (user_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: users_user_permissions users_user_permissio_permission_id_6d08dcd2_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users_user_permissions
    ADD CONSTRAINT users_user_permissio_permission_id_6d08dcd2_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: users_user_permissions users_user_permissions_user_id_92473840_fk_users_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users_user_permissions
    ADD CONSTRAINT users_user_permissions_user_id_92473840_fk_users_id FOREIGN KEY (user_id) REFERENCES public.users(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: -
--



--
-- PostgreSQL database dump complete
--

\unrestrict 0ZXP3qUXTxWcYDc3HworCnapMyc1yIvpNMoqI41ccURGGGLDaGdHe8ZPW38BSlI

