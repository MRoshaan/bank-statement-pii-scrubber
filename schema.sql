--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Debian 16.15-1.pgdg13+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg13+2)

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
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: analyses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.analyses (
    id uuid NOT NULL,
    batch_id uuid NOT NULL,
    model character varying(128) NOT NULL,
    prompt_version character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    result jsonb NOT NULL,
    markdown text NOT NULL,
    grounding_report jsonb NOT NULL,
    usage jsonb NOT NULL,
    error text,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: batches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.batches (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    file_count integer NOT NULL,
    raw_chars integer NOT NULL,
    scrubbed_chars integer NOT NULL,
    combined_text text NOT NULL,
    redaction_counts jsonb NOT NULL,
    facts jsonb NOT NULL,
    warnings jsonb NOT NULL
);


--
-- Name: chat_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_messages (
    id uuid NOT NULL,
    session_id uuid NOT NULL,
    role character varying(16) NOT NULL,
    content text NOT NULL,
    citations jsonb NOT NULL,
    grounding jsonb NOT NULL,
    model character varying(128),
    created_at timestamp with time zone NOT NULL
);


--
-- Name: chat_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_sessions (
    id uuid NOT NULL,
    batch_id uuid NOT NULL,
    title character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: redactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.redactions (
    id uuid NOT NULL,
    batch_id uuid NOT NULL,
    file_id uuid,
    entity_type character varying(64) NOT NULL,
    placeholder character varying(64) NOT NULL,
    count integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: statement_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.statement_files (
    id uuid NOT NULL,
    batch_id uuid NOT NULL,
    filename character varying(512) NOT NULL,
    format character varying(16) NOT NULL,
    size_bytes integer NOT NULL,
    sha256 character varying(64) NOT NULL,
    page_count integer,
    scrubbed_text text NOT NULL,
    redaction_counts jsonb NOT NULL,
    warnings jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transactions (
    id uuid NOT NULL,
    batch_id uuid NOT NULL,
    file_id uuid NOT NULL,
    txn_date date,
    txn_time character varying(16),
    description text NOT NULL,
    merchant character varying(255),
    category character varying(64) NOT NULL,
    amount numeric(18,2) NOT NULL,
    currency character varying(8) NOT NULL,
    direction character varying(8) NOT NULL,
    balance numeric(18,2),
    source_line integer,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: analyses analyses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analyses
    ADD CONSTRAINT analyses_pkey PRIMARY KEY (id);


--
-- Name: batches batches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batches
    ADD CONSTRAINT batches_pkey PRIMARY KEY (id);


--
-- Name: chat_messages chat_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_pkey PRIMARY KEY (id);


--
-- Name: chat_sessions chat_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_pkey PRIMARY KEY (id);


--
-- Name: redactions redactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.redactions
    ADD CONSTRAINT redactions_pkey PRIMARY KEY (id);


--
-- Name: statement_files statement_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statement_files
    ADD CONSTRAINT statement_files_pkey PRIMARY KEY (id);


--
-- Name: transactions transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (id);


--
-- Name: ix_analyses_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_analyses_batch_id ON public.analyses USING btree (batch_id);


--
-- Name: ix_chat_messages_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chat_messages_session_id ON public.chat_messages USING btree (session_id);


--
-- Name: ix_chat_sessions_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chat_sessions_batch_id ON public.chat_sessions USING btree (batch_id);


--
-- Name: ix_redactions_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_redactions_batch_id ON public.redactions USING btree (batch_id);


--
-- Name: ix_statement_files_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_statement_files_batch_id ON public.statement_files USING btree (batch_id);


--
-- Name: ix_transactions_batch_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_transactions_batch_category ON public.transactions USING btree (batch_id, category);


--
-- Name: ix_transactions_batch_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_transactions_batch_date ON public.transactions USING btree (batch_id, txn_date);


--
-- Name: ix_transactions_batch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_transactions_batch_id ON public.transactions USING btree (batch_id);


--
-- Name: ix_transactions_batch_merchant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_transactions_batch_merchant ON public.transactions USING btree (batch_id, merchant);


--
-- Name: ix_transactions_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_transactions_category ON public.transactions USING btree (category);


--
-- Name: ix_transactions_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_transactions_file_id ON public.transactions USING btree (file_id);


--
-- Name: ix_transactions_merchant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_transactions_merchant ON public.transactions USING btree (merchant);


--
-- Name: ix_transactions_txn_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_transactions_txn_date ON public.transactions USING btree (txn_date);


--
-- Name: analyses analyses_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analyses
    ADD CONSTRAINT analyses_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.batches(id) ON DELETE CASCADE;


--
-- Name: chat_messages chat_messages_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE;


--
-- Name: chat_sessions chat_sessions_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.batches(id) ON DELETE CASCADE;


--
-- Name: redactions redactions_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.redactions
    ADD CONSTRAINT redactions_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.batches(id) ON DELETE CASCADE;


--
-- Name: redactions redactions_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.redactions
    ADD CONSTRAINT redactions_file_id_fkey FOREIGN KEY (file_id) REFERENCES public.statement_files(id) ON DELETE CASCADE;


--
-- Name: statement_files statement_files_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statement_files
    ADD CONSTRAINT statement_files_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.batches(id) ON DELETE CASCADE;


--
-- Name: transactions transactions_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.batches(id) ON DELETE CASCADE;


--
-- Name: transactions transactions_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_file_id_fkey FOREIGN KEY (file_id) REFERENCES public.statement_files(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


