import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, login } from "@/api/client";

type Props = {
  onSuccess: () => void;
};

export function LoginPage({ onSuccess }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const origin =
    typeof window !== "undefined" ? window.location.origin : "(unknown)";

  const mut = useMutation({
    mutationFn: () => login({ email: email.trim(), password }),
    onSuccess: () => onSuccess(),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) return;
    mut.mutate();
  }

  let errorMsg: string | null = null;
  if (mut.isError) {
    const err = mut.error;
    if (err instanceof ApiError) {
      if (err.status === 0 || err.message.includes("Failed to fetch")) {
        errorMsg =
          "Cannot reach API (network or CORS). Origin may not be allowlisted yet.";
      } else if (err.status === 401) {
        errorMsg = err.body?.detail ?? "Invalid email or password";
      } else if (err.status === 429) {
        errorMsg = "Too many attempts — wait a moment";
      } else {
        errorMsg = err.message;
      }
    } else if (err instanceof TypeError) {
      errorMsg =
        "Cannot reach API (network or CORS). Origin may not be allowlisted yet.";
    } else {
      errorMsg = "Login failed";
    }
  }

  return (
    <div className="login">
      <p className="login__eyebrow">Banqueting kitchen</p>
      <h2 className="login__title">Sign in</h2>
      <p className="login__lead">
        One field pair. Token stays on this phone — no cookies.
      </p>

      <form className="login__form" onSubmit={onSubmit} noValidate>
        <div className="field">
          <label className="field__label" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            className="field__input"
            type="email"
            autoComplete="username"
            inputMode="email"
            enterKeyHint="next"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            className="field__input"
            type="password"
            autoComplete="current-password"
            enterKeyHint="go"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>

        {errorMsg ? <p className="field__error">{errorMsg}</p> : null}

        <button
          type="submit"
          className="btn btn--primary btn--block"
          disabled={mut.isPending || !email.trim() || !password}
        >
          {mut.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="login__origin">
        CORS origin (report to API allowlist)
        <strong>{origin}</strong>
      </div>
    </div>
  );
}
