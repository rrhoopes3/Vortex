/**
 * VRC-48M Camera App — Root Navigation
 *
 * Tab-based navigation with three main screens:
 * - Record: Camera + live anchoring
 * - Verify: Check a video against an anchor
 * - History: Browse past anchors
 *
 * Plus a stack-based ReviewScreen for post-recording results.
 */

import React from "react";
import { StatusBar, StyleSheet } from "react-native";
import { NavigationContainer } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";

import { RecordScreen } from "./screens/RecordScreen";
import { ReviewScreen } from "./screens/ReviewScreen";
import { VerifyScreen } from "./screens/VerifyScreen";
import { HistoryScreen } from "./screens/HistoryScreen";
import { COLORS } from "./utils/config";

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

function RecordStack() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: COLORS.bg },
        headerTintColor: COLORS.text,
        headerTitleStyle: { fontWeight: "700" },
        contentStyle: { backgroundColor: COLORS.bg },
      }}
    >
      <Stack.Screen
        name="RecordMain"
        component={RecordScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="Review"
        component={ReviewScreen}
        options={{ title: "Anchor Result" }}
      />
    </Stack.Navigator>
  );
}

export default function App() {
  return (
    <NavigationContainer
      theme={{
        dark: true,
        colors: {
          primary: COLORS.accent,
          background: COLORS.bg,
          card: COLORS.surface,
          text: COLORS.text,
          border: COLORS.border,
          notification: COLORS.red,
        },
        fonts: {
          regular: { fontFamily: "System", fontWeight: "400" },
          medium: { fontFamily: "System", fontWeight: "500" },
          bold: { fontFamily: "System", fontWeight: "700" },
          heavy: { fontFamily: "System", fontWeight: "800" },
        },
      }}
    >
      <StatusBar barStyle="light-content" />
      <Tab.Navigator
        screenOptions={{
          tabBarStyle: {
            backgroundColor: COLORS.surface,
            borderTopColor: COLORS.border,
            height: 85,
            paddingBottom: 28,
            paddingTop: 8,
          },
          tabBarActiveTintColor: COLORS.accent,
          tabBarInactiveTintColor: COLORS.muted,
          tabBarLabelStyle: {
            fontSize: 11,
            fontWeight: "600",
          },
          headerStyle: { backgroundColor: COLORS.bg },
          headerTintColor: COLORS.text,
        }}
      >
        <Tab.Screen
          name="Record"
          component={RecordStack}
          options={{
            headerShown: false,
            tabBarLabel: "Record",
            tabBarIcon: ({ color }) => (
              <TabIcon text="\uD83D\uDCF7" color={color} />
            ),
          }}
        />
        <Tab.Screen
          name="Verify"
          component={VerifyScreen}
          options={{
            title: "Verify",
            tabBarIcon: ({ color }) => (
              <TabIcon text="\uD83D\uDD0D" color={color} />
            ),
          }}
        />
        <Tab.Screen
          name="History"
          component={HistoryScreen}
          options={{
            title: "History",
            tabBarIcon: ({ color }) => (
              <TabIcon text="\uD83D\uDCCB" color={color} />
            ),
          }}
        />
      </Tab.Navigator>
    </NavigationContainer>
  );
}

function TabIcon({ text, color }: { text: string; color: string }) {
  return (
    <React.Fragment>
      {/* Using emoji as placeholder — replace with proper icons in production */}
      <StatusBar />
    </React.Fragment>
  );
}
