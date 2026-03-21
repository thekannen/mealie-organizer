import React, { useMemo, useState } from "react";
import Icon from "../../components/Icon";
import { api, userRoleLabel } from "../../utils.jsx";

export default function UsersPage({ users, session, onNotice, onError, onConfirm, refreshUsers }) {
  const [newUserUsername, setNewUserUsername] = useState("");
  const [newUserRole, setNewUserRole] = useState("Editor");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newUserForceReset, setNewUserForceReset] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [userSearch, setUserSearch] = useState("");
  const [resetPasswords, setResetPasswords] = useState({});
  const [resetForceResets, setResetForceResets] = useState({});
  const [expandedUser, setExpandedUser] = useState(null);

  const filteredUsers = useMemo(() => {
    const query = userSearch.trim().toLowerCase();
    if (!query) return users;
    return users.filter((item) => {
      const username = String(item.username || "");
      const inferredRole = username === session?.username ? "owner" : "editor";
      return `${username} ${inferredRole}`.toLowerCase().includes(query);
    });
  }, [users, userSearch, session]);

  function generateTemporaryPassword() {
    const upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    const lower = "abcdefghijkmnopqrstuvwxyz";
    const digits = "23456789";
    const all = upper + lower + digits + "!@#$%";
    const rng = (max) => {
      const buf = new Uint32Array(1);
      const limit = Math.floor(0x100000000 / max) * max;
      let v;
      do { crypto.getRandomValues(buf); v = buf[0]; } while (v >= limit);
      return v % max;
    };
    const pick = (s) => s[rng(s.length)];
    const required = [pick(upper), pick(lower), pick(digits)];
    for (let i = required.length; i < 14; i += 1) required.push(pick(all));
    for (let i = required.length - 1; i > 0; i -= 1) {
      const j = rng(i + 1);
      [required[i], required[j]] = [required[j], required[i]];
    }
    setNewUserPassword(required.join(""));
    setShowPassword(true);
  }

  async function createUser(event) {
    event.preventDefault();
    try {
      await api("/users", {
        method: "POST",
        body: { username: newUserUsername, password: newUserPassword, force_reset: newUserForceReset },
      });
      setNewUserUsername("");
      setNewUserRole("Editor");
      setNewUserPassword("");
      setNewUserForceReset(true);
      await refreshUsers();
      onNotice("User created.");
    } catch (exc) {
      onError(exc);
    }
  }

  async function resetUserPassword(usernameValue) {
    const nextPassword = String(resetPasswords[usernameValue] || "").trim();
    if (!nextPassword) {
      onError("Enter a replacement password first.");
      return;
    }
    try {
      await api(`/users/${encodeURIComponent(usernameValue)}/reset-password`, {
        method: "POST",
        body: { password: nextPassword, force_reset: resetForceResets[usernameValue] ?? false },
      });
      setResetPasswords((prev) => ({ ...prev, [usernameValue]: "" }));
      setResetForceResets((prev) => ({ ...prev, [usernameValue]: false }));
      await refreshUsers();
      onNotice(`Password reset for ${usernameValue}.`);
    } catch (exc) {
      onError(exc);
    }
  }

  function deleteUser(usernameValue) {
    onConfirm({
      message: `Remove user "${usernameValue}"? This cannot be undone.`,
      action: async () => {
        try {
          await api(`/users/${encodeURIComponent(usernameValue)}`, { method: "DELETE" });
          await refreshUsers();
          onNotice(`Removed ${usernameValue}.`);
        } catch (exc) {
          onError(exc);
        }
      },
    });
  }

  return (
    <section className="page-grid settings-grid users-grid">
      <article className="card">
        <h3>Create User</h3>

        <form className="run-form" onSubmit={createUser}>
          <label className="field">
            <span>Username</span>
            <input
              value={newUserUsername}
              onChange={(event) => setNewUserUsername(event.target.value)}
              placeholder="kitchen-tablet"
            />
          </label>

          <label className="field">
            <span>Role</span>
            <select value={newUserRole} onChange={(event) => setNewUserRole(event.target.value)}>
              <option value="Editor">Editor</option>
              <option value="Viewer">Viewer</option>
              <option value="Owner">Owner</option>
            </select>
          </label>

          <label className="field">
            <span>Temporary Password</span>
            <div className="password-row">
              <input
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                value={newUserPassword}
                onChange={(event) => setNewUserPassword(event.target.value)}
                placeholder="At least 8 characters"
              />
              <button type="button" className="ghost icon-btn" onClick={() => setShowPassword((v) => !v)} title={showPassword ? "Hide password" : "Show password"}>
                <Icon name={showPassword ? "eye-off" : "eye"} />
              </button>
              <button type="button" className="ghost" onClick={generateTemporaryPassword}>
                Generate
              </button>
            </div>
          </label>

          <label className="field checkbox-field">
            <input
              type="checkbox"
              checked={newUserForceReset}
              onChange={(e) => setNewUserForceReset(e.target.checked)}
            />
            <span>Force password reset on first login</span>
          </label>

          <button type="submit" className="primary">
            <Icon name="users" />
            Create User
          </button>
        </form>
      </article>

      <article className="card">
        <div className="card-head split">
          <h3>Current Users</h3>
          <label className="search-box">
            <Icon name="search" />
            <input
              value={userSearch}
              onChange={(event) => setUserSearch(event.target.value)}
              placeholder="Search"
            />
          </label>
        </div>

        <ul className="user-list">
          {filteredUsers.length === 0 ? (
            <li className="muted">No users found.</li>
          ) : (
            filteredUsers.map((item) => {
              const isMe = session?.username === item.username;
              const isOpen = expandedUser === item.username;
              return (
                <li key={item.username} className={`user-row${isOpen ? " open" : ""}`}>
                  <div className="user-row-header">
                    <button type="button" className="user-row-toggle" onClick={() => setExpandedUser(isOpen ? null : item.username)}>
                      <strong>{item.username}</strong>
                      <span className="user-row-meta">
                        <span className="status-pill neutral">{userRoleLabel(item.username, session?.username)}</span>
                        {isMe && <span className="status-pill success">You</span>}
                        {item.force_password_reset && <span className="status-pill warning" title="Must reset password on next login">Reset pending</span>}
                      </span>
                      <Icon name="chevron" className={`row-chevron${isOpen ? " rotated" : ""}`} />
                    </button>
                    {!isMe && (
                      <button type="button" className="ghost danger-text icon-btn" title="Remove user" onClick={() => deleteUser(item.username)}>
                        <Icon name="trash" />
                      </button>
                    )}
                  </div>
                  {isOpen && (
                    <div className="user-row-body">
                      <div className="password-row">
                        <input
                          type="text"
                          placeholder="New password"
                          value={resetPasswords[item.username] || ""}
                          onChange={(event) =>
                            setResetPasswords((prev) => ({ ...prev, [item.username]: event.target.value }))
                          }
                        />
                        <button className="ghost" onClick={() => resetUserPassword(item.username)}>
                          Reset Password
                        </button>
                      </div>
                      <label className="field checkbox-field" style={{ marginTop: "0.5rem" }}>
                        <input
                          type="checkbox"
                          checked={resetForceResets[item.username] ?? false}
                          onChange={(e) =>
                            setResetForceResets((prev) => ({ ...prev, [item.username]: e.target.checked }))
                          }
                        />
                        <span>Force password reset on next login</span>
                      </label>
                    </div>
                  )}
                </li>
              );
            })
          )}
        </ul>

        <p className="muted tiny">{users.length} user{users.length !== 1 ? "s" : ""}</p>
      </article>
    </section>
  );
}
